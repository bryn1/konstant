"""Load and validate catalog/types.yaml: THE one source for task types and their agents.

Every consumer (board type validation, gate, DoD check, generator) reads types through this
module; no other module may hold a table of types, agents or phases (DESIGN §6.1, principle 3).

Validation on load (structure, always): every type has exactly one agent and that agent belongs
to exactly one type (the 1:1 invariant); `orchestrator` is a role, never a type's agent;
`review_types` names known types; the type name `project` is reserved for project roots.
File cross-references (catalog/agents/<agent>.md, skills, workflows) are checked when
`check_files=True`; the board only needs type names and loads without them.

Gate vocabulary, validated on every load: each type's `keywords` regex, `read_only`,
`done_rows` and ordered `phases` (agent, step open|close, verdict file, parallel, when changed,
task); every phase agent is the agent of some type; verdict files end in `-verdict.md` and are
unique within a type; each type has a producer phase (its own agent, no step). Top level:
`surfaces`, `verdict_words`, `small_shapes`, `imperative`, `deliverable_signal`.

Level 5 (docs/LEVEL5.md 4.2): a type may be `flag_only` (reachable only with `--type`, never by
the classifier or a `[type:]` tag, never filed as a board job: `intake`), and a type or a phase
may name the `identity` its phases act as (default worker: a factory identity of
board/policy.py PHASE_IDENTITIES).

Catalog content, validated on every load: each type names its `workflow` (a file name under
catalog/workflows/) and its `skills` (names under catalog/skills/); `roles` gives the skills of a
role agent (the orchestrator). With `check_files=True` every named agent profile, skill and
workflow file must exist.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DELIVERABLES = ("build", "verdict", "doc")
STEPS = ("open", "close")
WHENS = ("changed",)
VERDICT_SUFFIX = "-verdict.md"
PHASE_KEYS = {"agent", "step", "verdict", "parallel", "when", "task", "identity"}
# role agents: no type's producer. The orchestrator drives a session; the scenario writer writes a
# job's holdout scenarios before any producer exists (docs/LEVEL5.md 3.4), run by holdout/author.py
ROLE_AGENTS = ("orchestrator", "scenario-writer")
RESERVED_TYPES = ("project",)
NAME_RE = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"     # skill / workflow names: lowercase-kebab


class CatalogError(Exception):
    """catalog/types.yaml is missing, malformed, or breaks an invariant."""


@dataclass
class Catalog:
    root: Path
    version: int
    types: dict
    review_types: list
    raw: dict = field(repr=False, default_factory=dict)

    def type_names(self) -> list:
        return list(self.types)

    def agent_of(self, type_name: str) -> str:
        return self.types[type_name]["agent"]

    def agents(self) -> list:
        return [t["agent"] for t in self.types.values()] + list(ROLE_AGENTS)

    def is_review_type(self, type_name: str) -> bool:
        return type_name in self.review_types

    # --- gate vocabulary -------------------------------------------------------------------
    def phases(self, type_name: str) -> list:
        """Ordered phases, each a dict with every PHASE_KEYS key filled (None/False defaults)."""
        ident = self.identity(type_name)
        return [{"agent": p["agent"], "step": p.get("step"), "verdict": p.get("verdict"),
                 "parallel": bool(p.get("parallel", False)), "when": p.get("when"),
                 "task": str(p.get("task") or ""), "identity": p.get("identity") or ident}
                for p in self.types[type_name]["phases"]]

    def identity(self, type_name: str) -> str:
        """The identity a type's phases (and its close-out) act as: worker unless it says."""
        return self.types[type_name].get("identity") or "worker"

    def flag_only(self, type_name: str) -> bool:
        return bool(self.types.get(type_name, {}).get("flag_only", False))

    def classifiable(self) -> list:
        """The types the classifier and a `[type:]` tag may pick (flag-only types excluded)."""
        return [t for t in self.types if not self.flag_only(t)]

    def is_producer(self, type_name: str, phase: dict) -> bool:
        """A producer writes the deliverable: no step, and either no verdict file or the type's
        own agent (a `test` run's tester produces the suite AND its verdict)."""
        return phase["step"] is None and (phase["verdict"] is None
                                          or phase["agent"] == self.agent_of(type_name))

    def verifying(self, type_name: str) -> list:
        return [p for p in self.phases(type_name) if p["verdict"]]

    def read_only(self, type_name: str) -> bool:
        return bool(self.types[type_name].get("read_only", False))

    def done_rows(self, type_name: str) -> bool:
        return bool(self.types[type_name].get("done_rows", False))

    def keywords(self, type_name: str) -> str:
        return self.types[type_name]["keywords"]

    def verdict_words(self) -> dict:
        return self.raw["verdict_words"]

    def surfaces(self) -> list:
        return list(self.raw["surfaces"])

    def small_shapes(self) -> list:
        return list(self.raw["small_shapes"])

    def imperative(self) -> str:
        return self.raw["imperative"]

    def deliverable_signal(self) -> str:
        return self.raw["deliverable_signal"]

    # --- catalog content ---------------------------------------------------------------------
    def workflow_of(self, type_name: str) -> str:
        return self.types[type_name]["workflow"]

    def skills_of(self, type_name: str) -> list:
        return list(self.types[type_name]["skills"])

    def type_of_agent(self, agent: str):
        """The type whose producer agent this is; None for a role agent (orchestrator)."""
        return next((t for t, spec in self.types.items() if spec["agent"] == agent), None)

    def agent_skills(self, agent: str) -> list:
        t = self.type_of_agent(agent)
        return self.skills_of(t) if t else list(self.raw.get("roles", {}).get(agent, {})
                                                .get("skills", []))

    def skill_names(self) -> list:
        """Every skill named anywhere in types.yaml, first-mention order, no duplicates."""
        seen: dict = {}
        for a in self.agents():
            for s in self.agent_skills(a):
                seen.setdefault(s, None)
        return list(seen)


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2] / "catalog"


def find_root(home: Path | None = None, configured: str = "") -> Path:
    """configured [catalog] path -> env KONSTANT_CATALOG -> <home>/catalog -> source tree."""
    candidates = []
    if configured:
        p = Path(configured)
        candidates.append(p if p.is_absolute() or home is None else home / p)
    env = os.environ.get("KONSTANT_CATALOG", "").strip()
    if env:
        candidates.append(Path(env))
    if home is not None:
        candidates.append(home / "catalog")
    candidates.append(_source_root())
    for c in candidates:
        if (c / "types.yaml").is_file():
            return c.resolve()
    raise CatalogError("catalog/types.yaml not found (looked in: "
                       + ", ".join(str(c) for c in candidates) + ")")


def _validate(data, root: Path, check_files: bool) -> Catalog:
    if not isinstance(data, dict):
        raise CatalogError("types.yaml: top level must be a mapping")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise CatalogError("types.yaml: 'version' must be an integer")
    types = data.get("types")
    if not isinstance(types, dict) or not types:
        raise CatalogError("types.yaml: 'types' must be a non-empty mapping")
    owner_of: dict = {}
    for name, spec in types.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise CatalogError(f"types.yaml: bad type name {name!r}")
        if name in RESERVED_TYPES:
            raise CatalogError(f"types.yaml: type name {name!r} is reserved")
        if not isinstance(spec, dict):
            raise CatalogError(f"types.yaml: type {name!r} must be a mapping")
        agent = spec.get("agent")
        if not isinstance(agent, str) or not agent:
            raise CatalogError(f"types.yaml: type {name!r} needs exactly one agent (a string)")
        if agent in ROLE_AGENTS:
            raise CatalogError(f"types.yaml: {agent!r} is a role, not the agent of type {name!r}")
        if agent in owner_of:
            raise CatalogError(f"types.yaml: agent {agent!r} is the agent of both "
                               f"{owner_of[agent]!r} and {name!r} (one agent per type)")
        owner_of[agent] = name
        if spec.get("deliverable") not in DELIVERABLES:
            raise CatalogError(f"types.yaml: type {name!r} deliverable must be one of "
                               f"{', '.join(DELIVERABLES)}")
        if not isinstance(spec.get("summary"), str) or not spec["summary"].strip():
            raise CatalogError(f"types.yaml: type {name!r} needs a summary")
    for name, spec in types.items():   # after the 1:1 pass, so an agent clash is named first
        _validate_gate(name, spec)
    _validate_phase_agents(types)
    _validate_vocabulary(data)
    _validate_content(data)
    review = data.get("review_types", [])
    if not isinstance(review, list) or any(r not in types for r in review):
        raise CatalogError("types.yaml: 'review_types' must list known types")
    cat = Catalog(root=root, version=version, types=types, review_types=list(review), raw=data)
    if check_files:
        missing = [f"agents/{a}.md" for a in cat.agents()
                   if not (root / "agents" / f"{a}.md").is_file()]
        missing += [f"skills/{s}/SKILL.md" for s in cat.skill_names()
                    if not (root / "skills" / s / "SKILL.md").is_file()]
        missing += [f"workflows/{w}.md" for w in dict.fromkeys(cat.workflow_of(t) for t in types)
                    if not (root / "workflows" / f"{w}.md").is_file()]
        if missing:
            raise CatalogError("catalog files missing: " + ", ".join(missing))
    return cat


def _regex(where: str, value) -> None:
    if not isinstance(value, str) or not value:
        raise CatalogError(f"types.yaml: {where} must be a non-empty regex string")
    try:
        re.compile(value)
    except re.error as exc:
        raise CatalogError(f"types.yaml: {where} is not a valid regex: {exc}") from exc


def _identity(where: str, value) -> None:
    from konstant.board.policy import PHASE_IDENTITIES
    if value is not None and value not in PHASE_IDENTITIES:
        raise CatalogError(f"types.yaml: {where} identity must be one of "
                           f"{', '.join(PHASE_IDENTITIES)}")


def _validate_gate(name: str, spec: dict) -> None:
    _regex(f"type {name!r} keywords", spec.get("keywords"))
    _identity(f"type {name!r}", spec.get("identity"))
    for key in ("read_only", "done_rows", "flag_only"):
        if not isinstance(spec.get(key, False), bool):
            raise CatalogError(f"types.yaml: type {name!r} {key} must be true or false")
    phases = spec.get("phases")
    if not isinstance(phases, list) or not phases:
        raise CatalogError(f"types.yaml: type {name!r} needs a non-empty phases list")
    verdicts, producer = set(), False
    for i, ph in enumerate(phases, 1):
        where = f"type {name!r} phase {i}"
        if not isinstance(ph, dict) or not isinstance(ph.get("agent"), str) or not ph["agent"]:
            raise CatalogError(f"types.yaml: {where} needs an agent")
        unknown = set(ph) - PHASE_KEYS
        if unknown:
            raise CatalogError(f"types.yaml: {where} has unknown key(s) {', '.join(sorted(unknown))}")
        if ph.get("step") not in (None,) + STEPS:
            raise CatalogError(f"types.yaml: {where} step must be one of {', '.join(STEPS)}")
        if ph.get("when") not in (None,) + WHENS:
            raise CatalogError(f"types.yaml: {where} when must be one of {', '.join(WHENS)}")
        if not isinstance(ph.get("parallel", False), bool):
            raise CatalogError(f"types.yaml: {where} parallel must be true or false")
        _identity(where, ph.get("identity"))
        v = ph.get("verdict")
        if v is not None:
            if not isinstance(v, str) or not re.fullmatch(r"[A-Z][A-Z0-9]*" + re.escape(VERDICT_SUFFIX), v):
                raise CatalogError(f"types.yaml: {where} verdict must look like NAME{VERDICT_SUFFIX}")
            if v in verdicts:
                raise CatalogError(f"types.yaml: {where} verdict file {v} is used twice in "
                                   f"type {name!r} (one verdict file per verifying phase)")
            verdicts.add(v)
        if ph.get("step") is None and ph["agent"] == spec.get("agent"):
            producer = True
    if not producer:
        raise CatalogError(f"types.yaml: type {name!r} has no producer phase (a phase run by "
                           f"its own agent {spec.get('agent')!r} without a step)")


def _validate_phase_agents(types: dict) -> None:
    agents = {spec["agent"] for spec in types.values()}
    for name, spec in types.items():
        for ph in spec["phases"]:
            if ph["agent"] not in agents:
                raise CatalogError(f"types.yaml: type {name!r} phase agent {ph['agent']!r} is "
                                   "not the agent of any type")


def _validate_vocabulary(data: dict) -> None:
    surfaces = data.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces or not all(isinstance(s, str) for s in surfaces):
        raise CatalogError("types.yaml: 'surfaces' must be a non-empty list of names")
    words = data.get("verdict_words")
    if not isinstance(words, dict) or set(words) != {"pass", "fail", "blocked"} or not all(
            isinstance(v, list) and v and all(isinstance(w, str) and w.isupper() for w in v)
            for v in words.values()):
        raise CatalogError("types.yaml: 'verdict_words' needs pass, fail and blocked lists of "
                           "UPPERCASE words")
    shapes = data.get("small_shapes")
    if not isinstance(shapes, list) or not shapes:
        raise CatalogError("types.yaml: 'small_shapes' must be a non-empty list of regexes")
    for i, shape in enumerate(shapes, 1):
        _regex(f"small_shapes[{i}]", shape)
    _regex("imperative", data.get("imperative"))
    _regex("deliverable_signal", data.get("deliverable_signal"))


def _names(where: str, value) -> None:
    if not isinstance(value, list) or not all(isinstance(v, str) and re.fullmatch(NAME_RE, v)
                                               for v in value):
        raise CatalogError(f"types.yaml: {where} must be a list of lowercase-kebab skill names")
    if len(set(value)) != len(value):
        raise CatalogError(f"types.yaml: {where} names a skill twice")


def _validate_content(data: dict) -> None:
    for name, spec in data["types"].items():
        wf = spec.get("workflow")
        if not isinstance(wf, str) or not re.fullmatch(NAME_RE, wf):
            raise CatalogError(f"types.yaml: type {name!r} needs a workflow (a lowercase-kebab "
                               "file name under catalog/workflows/)")
        _names(f"type {name!r} skills", spec.get("skills"))
    roles = data.get("roles", {})
    if not isinstance(roles, dict) or set(roles) - set(ROLE_AGENTS):
        raise CatalogError("types.yaml: 'roles' may only describe the role agents "
                           + ", ".join(ROLE_AGENTS))
    for agent, spec in roles.items():
        if not isinstance(spec, dict):
            raise CatalogError(f"types.yaml: roles.{agent} must be a mapping")
        _names(f"roles.{agent} skills", spec.get("skills", []))


def load(root: Path | None = None, check_files: bool = False) -> Catalog:
    root = Path(root) if root is not None else find_root()
    path = root / "types.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"{path} not found") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"{path}: {exc}") from exc
    return _validate(data, root, check_files)
