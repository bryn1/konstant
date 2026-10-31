"""The generic `command` adapter: any CLI agent that takes a prompt (argv, a file or stdin).

`[harness] command` is the argv template (DESIGN §9 placeholders, plus {model}); konstant renders
AGENTS.md (and the shared `.agents/skills/`) and enforces only its own checks. Examples
(docs/HARNESSES.md): opencode (`opencode run {prompt}`), aider
(`aider --yes-always --no-auto-commits --message-file {prompt_file}`). konstant cannot know what
such a CLI lets a phase do, so `doctor` WARNs: the reach is whatever that tool enforces.
"""
from __future__ import annotations

from konstant.harnesses.base import Adapter, Phase, Reach, build_argv


class Command(Adapter):
    name = "command"
    model_key = "{model} in your [harness] command"
    local_models = "whatever the tool supports (e.g. opencode or aider with an OpenAI base URL)"
    surfaces_doc = "AGENTS.md, .agents/skills/*/SKILL.md (if the tool reads them)"

    def __init__(self, template: str = "", stdin: bool = False):
        self.template, self.stdin = template, stdin

    def argv(self, ph: Phase) -> list:
        return build_argv(self.template, ph.values | {"model": ph.model}, self.stdin)

    def reach(self, hcfg: dict, perm: dict, jail: bool = True) -> Reach:
        none = ("none", "konstant cannot see or enforce what this tool allows; check its own "
                "permission settings")
        return Reach(edits=none, commands=none, reads=none,
                     user_level=("none", "the tool's own user-level config loads as usual"))
