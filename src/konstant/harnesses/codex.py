"""OpenAI Codex CLI (`codex exec`). Every flag and key checked against the installed
`codex exec --help` (codex-cli 0.142.x) and the official config reference + permissions docs
(docs/HARNESSES.md cites them); the permission profile was exercised with `codex sandbox -P`.

Reach: a named permissions profile `konstant`, passed with `-c` (the user's config.toml is not
loaded: `--ignore-user-config`; no execpolicy rules: `--ignore-rules`): the whole file system
readable, the workspace writable, konstant's machinery, `var/`, `.git/config` and `.git/hooks/` of
every project read-only, the privileged role tokens and the usual credential dirs unreadable, the
phase's own OUT and TMPDIR writable; `/tmp` is NOT writable. `approval_policy = "never"`: a denied
call is returned to the model, never escalated. Commands are not allow-listed (Codex has no
per-command allow list in exec mode): anything may run, inside that file boundary. Network is on
for commands, because the konstant CLI talks to the loopback board.
Local models: `[harness.endpoint] base_url` -> a custom `model_providers.konstant` entry; Codex
speaks only the Responses API (`wire_api = "responses"`), which vLLM, Ollama and recent llama.cpp
servers offer at /v1/responses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from konstant import machinery
from konstant.harnesses.base import (PRIVILEGED_TOKENS, PROTECTED_DIR_LIST,
                                     PROTECTED_FILE_LIST, Adapter, HarnessError, Phase, Reach,
                                     private_dir)

PROFILE = "konstant"


def _toml_str(s: str) -> str:
    if any(c in s for c in '"\\\n'):
        raise HarnessError(f"codex: the path {s!r} cannot be written into a codex -c value")
    return json.dumps(s)


def git_guards(ws: Path, cwd: Path) -> list:
    """`.git/config` and `.git/hooks/` of the phase's project and every workspace project: a
    writable .git/config turns a later git command into arbitrary execution (REVIEW F-07)."""
    roots = {cwd, ws}
    projects = ws / "projects"
    if projects.is_dir():
        roots |= {p for p in projects.iterdir() if p.is_dir()}
    out = []
    for r in sorted(roots):
        for g in machinery.git_guards(r):          # .git/config (a file), .git/hooks (a dir)
            if g.is_file():
                out.append(str(g))
            elif g.is_dir():
                out.append(str(g) + "/**")
    return out


def filesystem(ph: Phase) -> dict:
    """The `konstant` permission profile. Codex (bubblewrap) mounts each rule over an existing
    path and cannot create a mount point inside a read-only tree, so only existing paths are
    named and nothing is named twice: `var/` is read-only as a whole (the DB, run records, the
    tokens), then the three privileged tokens are denied and the phase's OUT and TMPDIR opened."""
    ws, run = ph.workspace, ph.run_dir
    fs = {":root": "read", str(ws): "write"}
    for d in PROTECTED_DIR_LIST:
        if not d.startswith("var") and (ws / d).is_dir():
            fs[f"{ws / d}/**"] = "read"
    for f in PROTECTED_FILE_LIST:
        if not f.startswith("var/") and (ws / f).is_file():
            fs[str(ws / f)] = "read"
    if (ws / "var").is_dir():
        fs[f"{ws / 'var'}/**"] = "read"
    for t in PRIVILEGED_TOKENS:
        if (ws / "var" / "secrets" / t).is_file():
            fs[str(ws / "var" / "secrets" / t)] = "deny"
    for g in git_guards(ws, ph.cwd):
        fs[g] = "read"
    for d in (run / "out", run / "tmp"):
        if d.is_dir():
            fs[f"{d}/**"] = "write"
    for c in machinery.credentials("codex"):       # its own ~/.codex minus auth.json stays
        if Path(c).expanduser().exists():
            fs[c] = "deny"
    return fs


def inline_table(d: dict) -> str:
    return "{" + ",".join(f"{_toml_str(k)}={_toml_str(v)}" for k, v in d.items()) + "}"


class Codex(Adapter):
    name = "codex"
    binary = "codex"
    stdin = True
    model_key = "-m <model> (e.g. gpt-5.4-mini); a local endpoint: [harness.endpoint]"
    local_models = ("[harness.endpoint] base_url -> -c model_providers.konstant (Responses API: "
                    "vLLM, Ollama, llama.cpp /v1/responses); [harness] model = the served name")
    surfaces_doc = ("AGENTS.md (project root = the workspace: project_root_markers = "
                    "[\"konstant.toml\"]), .agents/skills/*/SKILL.md")
    uses_endpoint = True

    def argv(self, ph: Phase) -> list:
        a = [self.binary, "exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
             "--ephemeral", "--color", "never",
             "-c", 'approval_policy="never"',
             "-c", f'default_permissions="{PROFILE}"',
             "-c", f"permissions.{PROFILE}.filesystem={inline_table(filesystem(ph))}",
             "-c", f"permissions.{PROFILE}.network.enabled=true",
             "-c", 'project_root_markers=["konstant.toml"]',
             "-c", "history.persistence=\"none\""]
        ep = ph.endpoint or {}
        if ep.get("base_url"):
            prov = {"name": "konstant endpoint", "base_url": ep["base_url"],
                    "wire_api": "responses"}
            if ep.get("api_key_env"):
                prov["env_key"] = ep["api_key_env"]
            a += ["-c", f"model_providers.konstant={inline_table(prov)}",
                  "-c", 'model_provider="konstant"']
        if ph.model:
            a += ["-m", ph.model]
        return a + ["-"]

    def env(self, ph: Phase) -> dict:
        return {"TMPDIR": str(ph.run_dir / "tmp")}

    def prepare(self, ph: Phase) -> None:
        private_dir(ph.run_dir / "tmp")

    def reach(self, hcfg: dict, perm: dict, jail: bool = True) -> Reach:
        return Reach(
            edits=("enforced", "permissions profile: writes only under the workspace (not /tmp), "
                   "konstant's machinery, var/, .git/config and .git/hooks/ read-only"),
            commands=("partial", "no per-command allow list in exec mode: any command runs, but "
                      "inside the same file boundary (bubblewrap + seccomp on Linux); network "
                      "is on (the konstant CLI needs the loopback board)"),
            reads=("enforced", "owner/orchestrator/verifier tokens, the credential and agent "
                   "homes konstant lists (docs/CONCEPTS.md) and ~/.codex/auth.json unreadable; "
                   "everything else readable"),
            user_level=user_level())


def user_level() -> tuple:
    home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    found = [str(p) for p in (home / "AGENTS.md", home / "skills",
                              Path("~/.agents/skills").expanduser()) if p.exists()]
    base = "config.toml (MCP servers, hooks, profiles, trust) and execpolicy rules skipped"
    if found:
        return ("partial", f"{base}; not skippable and present here: {', '.join(found)} "
                "(Codex may load them into a phase)")
    return ("enforced", f"{base}; no user-level AGENTS.md or skills present")
