"""Claude Code (`claude -p`). Every flag checked against the installed `claude --help` (2.1.x) and
the official settings / permissions / sandboxing docs (DESIGN §9 cites them).

Reach: `--permission-mode dontAsk` + the generated `.claude/settings.json` passed with `--settings`
(allow list = the whole reach; deny rules for konstant's machinery, `.git/`, privileged verbs;
Read tool confined to the working dirs). The Bash sandbox (bubblewrap + socat on Linux) confines
command writes to the workspace; without it the allow list alone decides. User-level settings,
hooks and MCP servers are skipped (`--setting-sources project,local --strict-mcp-config`); the
user-level CLAUDE.md memory is not a settings source and may still load.

Factory mode (docs/LEVEL5.md 2.1): the phase runs inside konstant.jail with CLAUDE_CONFIG_DIR set
to a fresh per-phase home (session transcripts, shell snapshots, its .claude.json; removed after
the phase), into which only ~/.claude/.credentials.json is bound, read-only (the jail masks the
rest of ~/.claude and ~/.claude.json). Claude Code's own Bash sandbox (bubblewrap + socat) runs
nested inside the jail when a nested bubblewrap starts there, socat is installed and the jail
gives the phase its own short /tmp (`sandbox_nests`; Claude Code's sandbox bridges are unix
sockets under TMPDIR, and a long TMPDIR fails them: measured live, L5-2). Otherwise the phase gets
the same settings without the `sandbox` block, so Claude Code's sandbox is off and konstant's jail
is the boundary (`doctor` says which). Without that, a sandbox that cannot start does NOT fall back
to unsandboxed Bash under these settings (allowUnsandboxedCommands = false): every Bash call is
denied and the phase cannot work - fail closed, but useless.
"""
from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path

from konstant.config import DEFAULTS
from konstant.harnesses.base import Adapter, Phase, Reach, build_argv, drop_home, phase_home

COMMAND = DEFAULTS["harness"]["command"]
CREDENTIAL = "~/.claude/.credentials.json"      # the only file of ~/.claude a jailed phase sees


def sandbox_nests(workspace=None) -> bool:
    """Whether Claude Code's Linux sandbox can start inside konstant's jail: a nested bubblewrap
    starts there (jail.nests), socat, its network relay, is installed, and the phase has the
    jail's own short /tmp (base.private_tmp: a workspace under /tmp keeps a long TMPDIR)."""
    from konstant import jail
    from konstant.harnesses.base import private_tmp
    if sys.platform == "darwin":
        return True
    return jail.nests() and shutil.which("socat") is not None and \
        (workspace is None or private_tmp(workspace))


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

    relocatable_home = True
    home_doc = ("factory mode: CLAUDE_CONFIG_DIR = a fresh directory per phase, removed after it; "
                "only ~/.claude/.credentials.json bound in, read-only")

    def argv(self, ph: Phase) -> list:
        return build_argv(self.template(ph.model), ph.values, False)

    def env(self, ph: Phase) -> dict:
        if not self.jails(ph):
            return {}
        return {"CLAUDE_CONFIG_DIR": str(phase_home(ph, "claude"))}

    def prepare(self, ph: Phase) -> None:
        if self.jails(ph):
            phase_home(ph, "claude")

    def cleanup(self, ph: Phase) -> None:
        drop_home(ph, "claude")

    def jail_rw(self, ph: Phase) -> list:
        return [phase_home(ph, "claude")]

    def jail_ro_binds(self, ph: Phase) -> list:
        return [(Path(CREDENTIAL).expanduser(), phase_home(ph, "claude") / ".credentials.json")]

    def confine(self, argv: list, ph: Phase) -> list:
        # the open profile's host_write shares the host /tmp: no short private TMPDIR to nest in
        if self.jails(ph) and not (sandbox_nests(ph.workspace) and not ph.conf.host_write):
            argv = without_sandbox(argv, ph)
        return super().confine(argv, ph)

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


def without_sandbox(argv: list, ph: Phase) -> list:
    """The plan's fallback when Claude Code's sandbox cannot nest in the jail (docs/LEVEL5.md
    2.1): the same generated settings minus the `sandbox` block, written into the phase's own home
    and passed with --settings instead; konstant's jail is then the boundary."""
    if "--settings" not in argv:
        return argv
    i = argv.index("--settings") + 1
    try:
        data = json.loads(Path(argv[i]).read_text(encoding="utf-8"))
    except (OSError, ValueError, IndexError):
        return argv                    # Claude Code itself reports an unreadable settings file
    data.pop("sandbox", None)
    path = phase_home(ph, "claude") / "konstant-settings.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return argv[:i] + [str(path)] + argv[i + 1:]
