"""Google Gemini CLI (`gemini`). Not exercised against a real install: implemented from the official
docs and source (docs/cli/cli-reference.md, docs/cli/headless.md, docs/reference/policy-engine.md,
docs/tools/file-system.md, docs/cli/skills.md, packages/cli/src/config/{config,settings}.ts,
packages/core/src/utils/paths.ts; docs/HARNESSES.md cites them). Its live smoke is NOT RUN.

Start: `gemini --approval-mode auto_edit --policy <workspace>/.gemini/konstant-policy.toml
--include-directories <workspace> [-m MODEL] -p "<short instruction>"` with the phase prompt on
stdin (`-p` is appended to stdin and forces non-interactive mode). `auto_edit` approves the file
edit tools, which work only inside the workspace directories (cwd + --include-directories); the
policy file allow-lists the konstant verbs, the local git verbs and the `[permissions] allow`
test runners for `run_shell_command`, denies edits to konstant's machinery and denies the file
tools that read (read_file, read_many_files, glob, search_file_content) under the sealed holdout
store var/holdout/; in
non-interactive mode every other call (`ask_user`) is denied. GEMINI_CLI_HOME points into
`var/harness/gemini/`, so the operator's settings, GEMINI.md memory, policies, extensions and MCP
servers never load; the generated `.gemini/settings.json` is copied in as that home's settings.
Factory mode (docs/LEVEL5.md 2.1): the phase runs inside konstant.jail (shell commands included)
with GEMINI_CLI_HOME set to a fresh per-phase home, removed after the phase.
Auth: GEMINI_API_KEY (or Vertex variables) in the environment; an OAuth login in ~/.gemini is not
visible to a phase. An allowed test runner runs agent code unconfined unless `--sandbox` (Docker or
Podman) is added through [harness] command.
"""
from __future__ import annotations

import json
import os
import re
import shutil

from konstant import machinery
from konstant.agents.settings import GIT_ALLOW, KONSTANT_ALLOW, KONSTANT_DENY
from konstant.harnesses.base import (PROTECTED_DIR_LIST, PROTECTED_FILE_LIST, Adapter, Phase,
                                     Reach, drop_home, harness_home, phase_home, private_dir)

POLICY = ".gemini/konstant-policy.toml"
READ_TOOLS = ["read_file", "read_many_files", "glob", "search_file_content"]
SETTINGS = ".gemini/settings.json"
_BASH = re.compile(r"^Bash\((.+?)(?: \*|\*)?\)$")


def settings_json(ws=None, enabled: bool = True) -> str:
    """The generated settings: AGENTS.md as the context file and, for a workspace with memory on,
    konstant's memory MCP server (konstant/memory/wiring.py; `ws` None: the form without it)."""
    from konstant.memory import wiring
    data = {"context": {"fileName": ["AGENTS.md"], "loadMemoryFromIncludeDirectories": True}}
    servers = wiring.gemini_servers(ws, enabled) if ws is not None else {}
    if servers:
        data["mcpServers"] = servers
    return json.dumps(data, indent=2) + "\n"


def _q(s: str) -> str:
    return json.dumps(s)              # a JSON string is a valid TOML basic string


def shell_prefixes(ws, allow: list) -> list:
    forms = ["bin/konstant", str(ws / "bin" / "konstant")]
    out = [f"{f} {v}" for f in forms for v in KONSTANT_ALLOW]
    out += [f"git {v}" for v in GIT_ALLOW]
    out += [f"{ws}/.venv/bin/python -m pytest"]
    for rule in allow:
        m = _BASH.match(rule)
        if m:
            out.append(m.group(1).strip())
    return list(dict.fromkeys(out))


def policy(ws, allow: list, header: str, conf=None, memory: bool = True) -> str:
    """The policy for `conf` (konstant/confinement.py; None = closed): open allows every shell
    command (priority 50, below every deny); the machinery and holdout denies are the integrity
    core and stay unless the owner turned it off."""
    from konstant import confinement
    conf = conf or confinement.CLOSED
    forms = ["bin/konstant", str(ws / "bin" / "konstant")]
    rows = [f"# {header}",
            "# konstant's Gemini CLI policy (passed with --policy; workspace-tier policies are "
            "disabled by Gemini CLI). In non-interactive mode anything not allowed is denied."]

    def rule(**kw):
        rows.append("")
        rows.append("[[rule]]")
        rows.extend(f"{k} = {v}" for k, v in kw.items())

    for prefix in shell_prefixes(ws, allow):
        rule(toolName=_q("run_shell_command"), commandPrefix=_q(prefix), decision=_q("allow"),
             priority="100")
    for f in forms:
        for verb in KONSTANT_DENY:
            rule(toolName=_q("run_shell_command"), commandPrefix=_q(f"{f} {verb}"),
                 decision=_q("deny"), priority="200")
    rule(toolName=_q("run_shell_command"), commandRegex=_q(r"konstant.*--as[ =]?(owner|verifier)"),
         decision=_q("deny"), priority="200")
    if memory:                 # exactly the memory MCP server's tools (memory/wiring.py)
        from konstant.memory import wiring
        for tool in wiring.TOOLS:
            rule(mcpName=_q(wiring.SERVER), toolName=_q(tool), decision=_q("allow"),
                 priority="100")
    if conf.open:              # the open profile: any command (the denies above still win)
        rule(toolName=_q("run_shell_command"), decision=_q("allow"), priority="50")
    if not conf.integrity:
        return "\n".join(rows) + "\n"
    paths = [re.escape(str(ws / d)) + "/" for d in PROTECTED_DIR_LIST if not d.startswith("var")]
    paths += [re.escape(str(ws / f)) + '"' for f in PROTECTED_FILE_LIST
              if not f.startswith("var/")]
    # all of var/ (tokens, DB, run records) except a run's own OUT (a run without a project)
    paths += [re.escape(str(ws / "var")) + "/(?!runs/[^/]+/out/)"]
    paths += [re.escape(str(ws)) + "/(?:.+/)?\\.git/"]
    rule(toolName='["write_file", "replace"]',
         argsPattern=_q('"file_path":"(?:' + "|".join(paths) + ")"),
         decision=_q("deny"), priority="300")
    # the sealed paths (machinery.SEALED: the holdout store, the memory vault): no file tool
    # reads, lists or searches them (LEVEL5 3.3); a shell command is outside the policy's reach
    # (the jail covers it)
    sealed = [re.escape(str(ws / d)) for d in machinery.SEALED]
    sealed += [re.escape(d) for d in machinery.SEALED]
    sealed += [re.escape(str(d)) for d in machinery.external_store(ws)]   # REVIEW L5-R1 H-04
    if sealed:
        rule(toolName=_q(READ_TOOLS), argsPattern=_q("(?:" + "|".join(sealed) + ")(?:/|\"|$)"),
             decision=_q("deny"), priority="300")
    return "\n".join(rows) + "\n"


class Gemini(Adapter):
    name = "gemini"
    binary = "gemini"
    stdin = True
    model_key = "-m <model> (e.g. gemini-2.5-flash)"
    local_models = ("no: Gemini CLI speaks the Gemini API only (an OpenAI-compatible endpoint "
                    "needs a translating gateway, not tested)")
    surfaces_doc = ("AGENTS.md (context.fileName), .agents/skills/*/SKILL.md (workspace tier), "
                    ".gemini/settings.json, .gemini/konstant-policy.toml (passed with --policy)")

    env_keys = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI",
                 "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_APPLICATION_CREDENTIALS")

    def argv(self, ph: Phase) -> list:
        a = [self.binary, "--approval-mode", "auto_edit", "--policy", str(ph.workspace / POLICY),
             "--include-directories", str(ph.workspace), "--output-format", "text"]
        for p in (*ph.conf.extra_read, *ph.conf.extra_write):    # file tools reach them too
            a += ["--include-directories", os.path.expanduser(p)]
        if ph.model:
            a += ["-m", ph.model]
        return a + ["-p", "Carry out the konstant phase given above."]

    relocatable_home = True
    home_doc = ("GEMINI_CLI_HOME relocated into var/harness/gemini; factory mode: a fresh "
                "directory per phase, removed after it")

    def _home(self, ph: Phase):
        if self.jails(ph):
            return phase_home(ph, "gemini")
        return harness_home(ph.workspace, "gemini")

    def env(self, ph: Phase) -> dict:
        return {"GEMINI_CLI_HOME": str(self._home(ph))}

    def prepare(self, ph: Phase) -> None:
        d = private_dir(self._home(ph) / ".gemini")
        src = ph.workspace / SETTINGS
        if src.is_file():
            shutil.copyfile(src, d / "settings.json")

    def cleanup(self, ph: Phase) -> None:
        drop_home(ph, "gemini")

    def jail_rw(self, ph: Phase) -> list:
        return [phase_home(ph, "gemini")]

    def files(self, gen, hcfg: dict) -> dict:
        mem = getattr(gen, "memory", True)
        return {SETTINGS: settings_json(gen.ws, mem),
                POLICY: policy(gen.ws, gen.perm.get("allow", []), gen.header,
                               getattr(gen, "conf", None), mem)}

    def reach(self, hcfg: dict, perm: dict, jail: bool = True) -> Reach:
        return Reach(
            edits=("enforced", "edit tools work only inside the workspace directories; the policy "
                   "denies konstant's machinery and .git/ (from the docs; not exercised live)"),
            commands=("partial", "policy allow list; ask_user = deny in non-interactive mode; an "
                      "allowed test runner runs agent code UNSANDBOXED unless --sandbox "
                      "(Docker/Podman)"),
            reads=("partial", "file tools confined to the workspace directories (var/secrets/ is "
                   "inside them); allowed commands read anything you can"),
            user_level=("enforced", "GEMINI_CLI_HOME relocated into var/harness/gemini: no user "
                        "settings, GEMINI.md memory, policies, extensions or MCP servers"))
