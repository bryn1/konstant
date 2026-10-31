"""Harness adapters: konstant runs headless phases through any of these agent CLIs
(docs/HARNESSES.md). `[harness] name` picks the default, `[harness.types.<type>]` overrides it for
the phases of that type's agent (e.g. the reviewer on another harness or model than the coder).
One source per fact: the types come from catalog/types.yaml, the choice from konstant.toml."""
from __future__ import annotations

from dataclasses import dataclass

from konstant.config import DEFAULTS, HARNESS_NAMES
from konstant.harnesses.base import Adapter, HarnessError, Phase, Reach, build_argv
from konstant.harnesses.claude import Claude
from konstant.harnesses.codex import Codex
from konstant.harnesses.command import Command
from konstant.harnesses.dsh import Dsh
from konstant.harnesses.gemini import Gemini

ADAPTERS = {"claude": Claude, "codex": Codex, "gemini": Gemini, "dsh": Dsh, "command": Command}
assert tuple(ADAPTERS) == HARNESS_NAMES
DEFAULT_COMMAND = DEFAULTS["harness"]["command"]

__all__ = ["ADAPTERS", "Adapter", "Choice", "HarnessError", "Phase", "Reach", "build_argv",
           "configured", "resolve", "check_types", "adapter"]


def adapter(name: str) -> Adapter:
    if name not in ADAPTERS:
        raise HarnessError(f"unknown harness {name!r}: one of {', '.join(ADAPTERS)}")
    return ADAPTERS[name]()


@dataclass
class Choice:
    """The harness one phase runs on."""
    name: str
    model: str
    template: str | None          # an explicit argv template (yours), else the adapter's own
    stdin: bool
    where: str                    # "[harness]" or "[harness.types.<t>]" (for messages)

    @property
    def adapter(self) -> Adapter:
        if self.name == "command":
            return Command(self.template or "", self.stdin)
        return ADAPTERS[self.name]()


def _explicit(hcfg: dict) -> str | None:
    cmd = hcfg.get("command", DEFAULT_COMMAND)
    return None if cmd == DEFAULT_COMMAND else cmd


def resolve(hcfg: dict, type_name: str | None = None) -> Choice:
    """Default harness, or the override of `type_name`. A per-type row inherits the default
    model and command only when it keeps the default harness."""
    name, model, template = hcfg["name"], hcfg.get("model", ""), _explicit(hcfg)
    where = "[harness]"
    row = (hcfg.get("types") or {}).get(type_name) if type_name else None
    if row:
        where = f"[harness.types.{type_name}]"
        same = row.get("name", name) == name
        name = row.get("name", name)
        model = row.get("model", model if same else "")
        template = row["command"] if row.get("command") else (template if same else None)
    if name == "command" and not template:
        raise HarnessError(f"{where} name = \"command\" needs a command (an argv template with "
                           "{prompt}, {prompt_file} or stdin = true)")
    if template is not None and model and "{model}" not in template:
        raise HarnessError(f"{where} sets model = {model!r} but its command has no {{model}} "
                           "placeholder")
    stdin = hcfg.get("stdin", False) if template is not None else ADAPTERS[name].stdin
    return Choice(name, model, template, stdin, where)


def configured(hcfg: dict) -> list:
    """Every harness name the toml uses: the default, then the per-type overrides."""
    names = [hcfg["name"]] + [r.get("name", hcfg["name"]) for r in
                              (hcfg.get("types") or {}).values()]
    return list(dict.fromkeys(names))


def check_types(hcfg: dict, cat) -> None:
    """[harness.types.<t>] must name a catalog type (catalog/types.yaml is the one source)."""
    for t in (hcfg.get("types") or {}):
        if t not in cat.types:
            raise HarnessError(f"[harness.types.{t}]: {t!r} is not a task type in "
                               f"catalog/types.yaml ({', '.join(cat.type_names())})")
