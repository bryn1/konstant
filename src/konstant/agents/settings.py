"""The generated `.claude/settings.json`: Claude Code's reach, WORKSPACE-SCOPED (design decision:
a headless phase may edit files and run commands only inside the workspace; DESIGN §8-9). Every key
below was checked against `claude --help` (2.1.x) and the official settings / permissions /
sandboxing docs (DESIGN §9 names them).

- permissions.allow: Read/Edit rules for `//<workspace>/**` only (a `//` prefix is an absolute
  path; a single `/` would anchor at the settings file's directory), the konstant verbs a phase
  needs, read-only-ish git verbs, and the `[permissions] allow` rules of konstant.toml (test runners).
  Under `--permission-mode dontAsk` anything not allowed is denied, so this list IS the reach.
- permissions.deny: konstant's own machinery, from konstant/machinery.py (bin/, .venv/, src/,
  catalog/, tests/, install.sh, pyproject.toml, konstant.toml, every generated harness surface:
  .claude/, .agents/, .dsh/, .gemini/, AGENTS.md, CLAUDE.md; var/harness/, the token files, the
  board DB, run records, phase manifests and profile snapshots), every `.git/` directory of the workspace (a `.git/config`
  edit turns an allowed `git status` into arbitrary execution through a filter or a hook;
  REVIEW F-07), the konstant verbs that act as another role (verify, verdict, approve) or start
  more agents (task run, board, agents sync), and `--as owner|verifier` anywhere on a konstant
  command line. Deny rules are evaluated before allow rules, so they carve holes in the
  workspace allow.
- the sealed paths (machinery.SEALED: the holdout store var/holdout/ and the memory vault
  memory/): Read denied for the file tools and read-denied in the sandbox, next to var/secrets/
  (docs/LEVEL5.md 3.3). Memory is reached through the `konstant-memory` MCP server, whose three
  tools are allowed by name (konstant/memory/wiring.py), or the `konstant memory` verbs.
- permissions.blockReadsOutsideWorkingDirectories: file tools refuse reads outside the working
  directories (the phase's project dir + the workspace via `--add-dir`).
- permissions.disableBypassPermissionsMode: no session in this workspace may skip permissions.
- sandbox: Bash runs inside Claude Code's OS sandbox (bubblewrap + socat on Linux) with writes
  confined to the workspace and the usual credential locations read-denied; the allow list stays
  authoritative inside it (autoAllowBashIfSandboxed = false; REVIEW F-19); no unsandboxed retry;
  konstant verbs that talk to the loopback board are excluded (a sandboxed command cannot reach a
  host server on Linux) - `task check` among them runs any agent code it executes inside
  konstant.jail, the same bubblewrap boundary (REVIEW F-06). If the sandbox cannot start, Claude
  Code falls back to unsandboxed Bash (failIfUnavailable = false) and the allow list alone
  decides: an allowed test runner then runs agent-written code with the user's full rights, so the
  allow list does NOT confine a phase (docs/CONCEPTS.md "Security model and limits").
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

from konstant import machinery

SCHEMA = "https://json.schemastore.org/claude-code-settings.json"
# konstant verbs a phase agent may run (board bookkeeping + the gate's own judge/check)
# (`job *` includes `job verdict` / `job approve`; the deny list below removes them, deny wins)
KONSTANT_ALLOW = ("job", "task classify", "task gate", "task check", "task judge",
                  "project list", "agents list", "version", "memory recall", "memory store",
                  "memory note", "memory list", "memory show", "memory log")
# konstant verbs that act as another role or start more agents: never from inside a session
KONSTANT_DENY = ("task run", "verify", "job verdict", "job approve", "board", "agents sync",
                 "memory reindex")
# (no `init`: `git init <path>` writes anywhere; a project is initialised by `project add`)
GIT_ALLOW = ("status", "diff", "log", "show", "add", "commit", "restore", "mv", "rm",
             "rev-parse", "ls-files", "branch", "switch", "stash")
# workspace paths no session may write: konstant/machinery.py, the one source every adapter and
# konstant.jail read (G-03: the generated surfaces of the other harnesses and var/harness/ belong
# here too)
PROTECTED_DIRS = machinery.DIRS
PROTECTED_FILES = machinery.FILES
# read-denied in the sandbox (outside the workspace; the Read tool is already confined to it):
# the static list (a rendered file must not depend on the environment of `agents sync`); Claude
# Code's own ~/.claude stays readable to its sandboxed shell, minus its credentials file
CREDENTIALS = tuple(machinery.credentials("claude", env={}))
_RULE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\((.+)\))?$")
_BROAD = {"Bash", "Bash(*)", "Edit", "Edit(*)", "Read", "Read(*)", "Write", "NotebookEdit",
          "Edit(//**)", "Read(//**)", "Edit(**)", "Read(**)", "Edit(/**)", "Read(/**)"}


class SettingsError(Exception):
    """A `[permissions]` rule in konstant.toml would widen the reach past the workspace."""


def abs_rule(path: Path) -> str:
    """`/srv/ws` -> `//srv/ws` (Claude Code's absolute-path prefix for Read/Edit rules)."""
    return "//" + str(path).lstrip("/")


def check_rule(rule: str, workspace: Path) -> None:
    m = _RULE.match(rule)
    if not m:
        raise SettingsError(f"[permissions] allow: {rule!r} is not a Tool or Tool(specifier) rule")
    if rule in _BROAD:
        raise SettingsError(f"[permissions] allow: {rule!r} grants the whole tool; name the "
                            "command, e.g. 'Bash(npm test *)'")
    spec = m.group(2) or ""
    if rule.startswith(("Read(", "Edit(")):
        ws = abs_rule(workspace)
        inside = spec.startswith(ws + "/") or spec.startswith("./")
        if not inside or ".." in spec.split("/"):
            raise SettingsError(f"[permissions] allow: {rule!r} reaches outside the workspace; "
                                f"write '{ws}/<path>' or './<path>'")
    if rule.startswith("Bash(") and spec.lstrip().startswith("*"):
        raise SettingsError(f"[permissions] allow: {rule!r} puts a wildcard before the command")


def _konstant_forms(workspace: Path, python: str) -> list:
    return ["bin/konstant", str(workspace / "bin" / "konstant"),
            shlex.join([python, "-m", "konstant"])]


def render(workspace: Path, perm: dict, python: str | None = None, conf=None,
           memory: bool = True) -> str:
    """The settings for `conf` (konstant/confinement.py; None = closed, the 0.1.0 reach).
    `memory` ([memory] enabled): allow exactly the memory MCP server's tools
    (konstant/memory/wiring.py), the server `--mcp-config` names."""
    from konstant.memory import wiring
    from konstant import confinement
    conf = conf or confinement.CLOSED
    workspace = Path(workspace)
    python = python or sys.executable
    for rule in perm.get("allow", []):
        check_rule(rule, workspace)
    ws = abs_rule(workspace)
    forms = _konstant_forms(workspace, python)
    allow = [f"Read({ws}/**)", f"Edit({ws}/**)"]
    allow += [f"Bash({f} {verb} *)" for f in forms for verb in KONSTANT_ALLOW]
    allow += [f"Bash(git {verb} *)" for verb in GIT_ALLOW]
    allow += [f"Bash({workspace}/.venv/bin/python -m pytest *)"]
    allow += [r for r in perm.get("allow", []) if r not in allow]
    allow += reach_allow(conf)
    allow += wiring.claude_allow(memory)
    deny = []
    if conf.integrity:
        deny += [f"Read({ws}/var/secrets/**)"]
        deny += [f"Read({ws}/{d}/**)" for d in machinery.SEALED]  # the holdout store (LEVEL5 3.3)
        deny += [f"Edit({ws}/{d}/**)" for d in PROTECTED_DIRS]
        deny += [f"Edit({ws}/{f})" for f in PROTECTED_FILES]
        deny += [f"Edit({ws}/var/runs/*/{r})" if "." in r else f"Edit({ws}/var/runs/*/{r}/**)"
                 for r in machinery.RUN_RECORDS]
        deny += [f"Edit({ws}/**/.git/**)", f"Edit({ws}/.git/**)"]
    deny += [f"Bash({f} {verb} *)" for f in forms for verb in KONSTANT_DENY]
    deny += [f"Bash({f} *--as {r}*)" for f in forms for r in ("owner", "verifier")]
    deny += [f"Bash({f} *--as={r}*)" for f in forms for r in ("owner", "verifier")]
    deny = list(dict.fromkeys(deny))
    perms = {"allow": list(dict.fromkeys(allow)), "deny": deny,
             "blockReadsOutsideWorkingDirectories": not conf.open,
             "disableBypassPermissionsMode": "disable"}
    extra = [abs_rule(Path(os.path.expanduser(p))) for p in
             (*conf.extra_read, *conf.extra_write, *_cred_files(conf))]
    if extra and not conf.open:
        perms["additionalDirectories"] = list(dict.fromkeys(extra))
    data = {"$schema": SCHEMA, "permissions": perms}
    if perm.get("sandbox", True):
        data["sandbox"] = sandbox_block(workspace, forms, conf)
    return json.dumps(data, indent=2) + "\n"


def _cred_files(conf) -> list:
    return [c for c in conf.credentials if c != "*" and not c.startswith("$")]


def reach_allow(conf) -> list:
    """The allow rules the confinement adds (closed adds none)."""
    out = []
    if conf.open:
        out += ["Bash", "Read(//**)"]
    if conf.host_write:
        out += ["Edit(//**)"]
    elif conf.home_write:
        out += ["Edit(~/**)"]
    for p in (*conf.extra_read, *_cred_files(conf)):
        out.append(f"Read({abs_rule(Path(os.path.expanduser(p)))}/**)")
    for p in conf.extra_write:
        r = abs_rule(Path(os.path.expanduser(p)))
        out += [f"Read({r}/**)", f"Edit({r}/**)"]
    return out


def sandbox_block(workspace: Path, forms: list, conf) -> dict:
    """Claude Code's Bash sandbox for `conf`: writes, reads, unix sockets and network."""
    passed = {os.path.realpath(os.path.expanduser(c)) for c in conf.cred_paths(env={})}
    deny_read = [str(workspace / "var" / "secrets"), *(str(p) for p in
                                                       machinery.sealed(workspace))] \
        if conf.integrity else []
    deny_read += [c for c in CREDENTIALS
                  if os.path.realpath(os.path.expanduser(c)) not in passed]
    allow_read = []
    if not conf.home_read:
        deny_read.append("~/")
        allow_read += [str(workspace), *conf.extra_read, *_cred_files(conf)]
    write = [str(workspace)] + (["/"] if conf.host_write else ["~/"] if conf.home_write else [])
    write += list(conf.extra_write)
    fs = {"allowWrite": write,
          "denyWrite": [str(workspace / p) for p in PROTECTED_DIRS + PROTECTED_FILES]
          if conf.integrity else [],
          "denyRead": deny_read}
    if allow_read:
        fs["allowRead"] = list(dict.fromkeys(allow_read))
    box = {"enabled": True, "autoAllowBashIfSandboxed": False, "allowUnsandboxedCommands": False,
           "failIfUnavailable": False,
           "excludedCommands": [f"{f} {verb} *" for f in forms for verb in KONSTANT_ALLOW],
           "filesystem": fs}
    net = {}
    if conf.network is True:
        net.update(allowedDomains=["*"], allowLocalBinding=True)
    elif conf.network is False:
        net["allowedDomains"] = []
    if conf.ssh_agent:          # SSH_AUTH_SOCK changes per login: a static file cannot name it
        net["allowAllUnixSockets"] = True
    elif conf.docker_socket:
        net["allowUnixSockets"] = list(machinery.DOCKER_SOCKETS)
    if net:
        box["network"] = net
    return box
