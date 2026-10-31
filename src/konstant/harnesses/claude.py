"""Claude Code (`claude -p`). Every flag checked against the installed `claude --help` (2.1.x) and
the official settings / permissions / sandboxing docs (DESIGN §9 cites them).

Reach: `--permission-mode dontAsk` + the generated `.claude/settings.json` passed with `--settings`
(allow list = the whole reach; deny rules for konstant's machinery, `.git/`, privileged verbs;
Read tool confined to the working dirs). The Bash sandbox (bubblewrap + socat on Linux) confines
command writes to the workspace; without it the allow list alone decides. User-level settings,
hooks and MCP servers are skipped (`--setting-sources project,local --strict-mcp-config`); the
user-level CLAUDE.md memory is not a settings source and may still load.
"""
from __future__ import annotations

import shlex
import shutil
import sys

from konstant.config import DEFAULTS
from konstant.harnesses.base import Adapter, Phase, Reach, build_argv

COMMAND = DEFAULTS["harness"]["command"]


class Claude(Adapter):
    name = "claude"
    binary = "claude"
    instructions = "CLAUDE.md"
    model_key = "--model <name> (aliases such as haiku, sonnet, opus, or a full model id)"
    local_models = ("Anthropic Messages API only: an Anthropic-compatible gateway in front of a "
                    "local server (e.g. LiteLLM) via ANTHROPIC_BASE_URL in [harness] env; not "
                    "tested by konstant")
    surfaces_doc = ("CLAUDE.md, .claude/agents/*.md, .claude/skills/*/SKILL.md, "
                    ".claude/settings.json (passed with --settings)")

    def template(self, model: str = "") -> str:
        if not model:
            return COMMAND
        head, rest = COMMAND.split(" ", 2)[:2], COMMAND.split(" ", 2)[2]
        return " ".join(head + ["--model", shlex.quote(model), rest])

    def argv(self, ph: Phase) -> list:
        return build_argv(self.template(ph.model), ph.values, False)

    def reach(self, hcfg: dict, perm: dict, jail: bool = True) -> Reach:
        sandboxed = perm.get("sandbox", True) and (
            sys.platform == "darwin" or all(shutil.which(b) for b in ("bwrap", "socat")))
        cmd = (("enforced", "allow list under dontAsk; Bash sandbox confines writes to the "
                "workspace") if sandboxed else
               ("partial", "allow list under dontAsk, but Bash runs UNSANDBOXED (no bubblewrap/"
                "socat or [permissions] sandbox = false): an allowed test runner executes "
                "agent-written code with your full rights"))
        return Reach(
            edits=("enforced", "Edit allowed only under the workspace, minus konstant's machinery, "
                   ".git/, catalog/, tests/ and run records"),
            commands=cmd,
            reads=("enforced", "Read tool confined to the working dirs; var/secrets/ and "
                   "credential dirs denied to the Read tool and to sandboxed commands") if sandboxed else
                  ("partial", "Read tool confined and var/secrets/ denied, but an allowed "
                   "unsandboxed test runner can read anything you can"),
            user_level=user_level())


def user_level() -> tuple:
    from pathlib import Path
    mem = Path("~/.claude/CLAUDE.md").expanduser()
    if mem.is_file():
        return ("partial", f"user settings, hooks and MCP servers skipped; your user-level memory "
                f"{mem} is not a settings source and loads into every phase")
    return ("enforced", "user settings, hooks and MCP servers skipped; no user-level "
            "~/.claude/CLAUDE.md memory present")
