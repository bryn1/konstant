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
import re
import shlex
import sys
from pathlib import Path

from konstant import machinery

SCHEMA = "https://json.schemastore.org/claude-code-settings.json"
# konstant verbs a phase agent may run (board bookkeeping + the gate's own judge/check)
# (`job *` includes `job verdict` / `job approve`; the deny list below removes them, deny wins)
KONSTANT_ALLOW = ("job", "task classify", "task gate", "task check", "task judge",
                  "project list", "agents list", "version")
# konstant verbs that act as another role or start more agents: never from inside a session
KONSTANT_DENY = ("task run", "verify", "job verdict", "job approve", "board", "agents sync")
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


def render(workspace: Path, perm: dict, python: str | None = None) -> str:
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
    deny = [f"Read({ws}/var/secrets/**)"]
    deny += [f"Edit({ws}/{d}/**)" for d in PROTECTED_DIRS]
    deny += [f"Edit({ws}/{f})" for f in PROTECTED_FILES]
    deny += [f"Edit({ws}/var/runs/*/{r})" if "." in r else f"Edit({ws}/var/runs/*/{r}/**)"
             for r in machinery.RUN_RECORDS]
    deny += [f"Edit({ws}/**/.git/**)", f"Edit({ws}/.git/**)"]
    deny += [f"Bash({f} {verb} *)" for f in forms for verb in KONSTANT_DENY]
    deny += [f"Bash({f} *--as {r}*)" for f in forms for r in ("owner", "verifier")]
    deny += [f"Bash({f} *--as={r}*)" for f in forms for r in ("owner", "verifier")]
    deny = list(dict.fromkeys(deny))
    data = {
        "$schema": SCHEMA,
        "permissions": {
            "allow": allow,
            "deny": deny,
            "blockReadsOutsideWorkingDirectories": True,
            "disableBypassPermissionsMode": "disable",
        },
    }
    if perm.get("sandbox", True):
        data["sandbox"] = {
            "enabled": True,
            "autoAllowBashIfSandboxed": False,
            "allowUnsandboxedCommands": False,
            "failIfUnavailable": False,
            "excludedCommands": [f"{f} {verb} *" for f in forms for verb in KONSTANT_ALLOW],
            "filesystem": {
                "allowWrite": [str(workspace)],
                "denyWrite": [str(workspace / p) for p in PROTECTED_DIRS + PROTECTED_FILES],
                "denyRead": [str(workspace / "var" / "secrets"), *CREDENTIALS],
            },
        }
    return json.dumps(data, indent=2) + "\n"
