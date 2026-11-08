"""Size tiers (docs/CONCEPTS.md "Triage"): deterministic, no model, on top of the type classifier.

  inline   small: the orchestrator answers in its own session (the classifier's `small`)
  agent    medium: one typed run with its workflow
  fanout   large: N parallel typed runs, one per independent part, N <= the cap
  max      huge: as many parallel typed runs as the cap allows, never more
  factory  a long-running goal: goal -> intake -> jobs -> holdouts -> ship, until the goal's
           acceptance is met or every job used its max_attempts

Order (first match wins):
  1. `[tier:<name>]` in the task (the owner's override). On a typed task any tier; on a small task
     a tier other than inline gates it (the type from the keywords, else `code`). `factory` on a
     run bound to one job is `agent` (a job is one unit of work; a goal is filed with `goal add`).
  2. small -> inline (why: the classifier's reason).
  3. factory: a long-running signal ("for a week", "until all tests pass", "keep running", ...)
     AND a mechanical acceptance (PROBE:/VERIFY_CMD: rows, a DoD section, "until <tests> pass")
     AND a type the factory can ship (deliverable `build`, not in `[ship] decision_types`).
     A long-running signal without the other two is NOT factory: the tier says why
     (`factory-unsuitable: ...`) and the size rules decide.
  4. max: a whole-scope signal ("the entire codebase", "every module", "all services", ...), or
     more independent parts than the cap.
  5. fanout: at least `[triage] fanout_min` independent parts (list items, distinct file paths, an
     explicit count such as "12 modules"), counted before the DoD section.
  6. agent.

The cap: `[harness] max_concurrency` is the number of requests the configured endpoint serves at
once (its slots). A typed run itself runs up to `[harness] max_parallel` phases at once, so at most
max_concurrency // max_parallel typed runs fit (at least 1). Unset (0): the endpoint's slots are
unknown and konstant assumes max_parallel, i.e. ONE run at a time. More agents than slots evict
each other's prompt cache and finish later in total, so `max` is never unbounded.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

TIERS = ("inline", "agent", "fanout", "max", "factory")
TAG = re.compile(r"\[tier:([a-z_-]+)\]", re.I)

LIST_ITEM = re.compile(r"(?m)^\s*(?:[-*•]|\d{1,3}[.)])\s+\S")
EXTS = ("py|md|ts|tsx|js|jsx|mjs|go|rs|java|kt|c|h|cc|cpp|hpp|rb|php|sh|ya?ml|toml|json|sql|"
        "html|css|scss|vue|svelte|swift|cs|ex|exs|lua|tf")
PATH = re.compile(r"(?<![\w/.-])(?:[\w.-]+/)*[\w-]+\.(?:" + EXTS + r")\b")
UNITS = (r"files|modules|packages|services|endpoints|pages|components|repos|repositories|"
         r"projects|crates|tests|parts|tasks|scripts|commands|routes|tables|screens|libraries|"
         r"apps|handlers|plugins|adapters|microservices")
NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
           "thirty": 30, "fifty": 50, "hundred": 100}
COUNT = re.compile(r"\b(\d{1,4}|" + "|".join(NUMBERS) + r")\s+(?:[a-z-]+\s+){0,2}(?:" + UNITS
                   + r")\b", re.I)
HUGE = re.compile(r"\b(?:(?:the\s+)?(?:entire|whole)\s+(?:code\s?base|repo|repository|project|"
                  r"monorepo|system|application|app|product)|every\s+(?:single\s+)?(?:file|module|"
                  r"package|service|endpoint|component|page|repo|repository|project)|all\s+(?:the\s+"
                  r")?(?:files|modules|packages|services|endpoints|components|pages|repos|"
                  r"repositories|projects)|(?:code\s?base|repo|project|fleet)[- ]wide|across\s+"
                  r"(?:the\s+)?(?:whole\s+|entire\s+)?(?:code\s?base|repo|repository|monorepo))\b",
                  re.I)
LONG_RUNNING = re.compile(r"\b(?:(?:for|over)\s+(?:a|one|two|three|several|\d+)\s+(?:weeks?|"
                          r"months?)|(?:a|one)\s+(?:week|month)\s+straight|keep\s+(?:going|"
                          r"running|working|at\s+it)|run\s+(?:continuously|unattended|"
                          r"overnight|for\s+days)|until\s+(?:all|every|the|it|they|each)\b|"
                          r"dark\s+factory|long[- ]running|day\s+and\s+night|non-?stop)\b", re.I)
ACCEPTANCE = re.compile(r"(?m)(?:^\s*(?:PROBE|VERIFY_CMD):|^\s*(?:#+\s*)?(?:DoD|Definition of "
                        r"Done|Acceptance(?: criteria)?)\s*:?\s*$|\buntil\s+(?:all\s+|the\s+|"
                        r"every\s+)?(?:\w+\s+){0,3}(?:tests?|checks?|probes?|holdouts?|builds?)"
                        r"\s+(?:pass|passes|are\s+green|is\s+green|succeed)\b)", re.I)
DOD_START = re.compile(r"(?mi)^\s*(?:#+\s*)?(?:DoD|Definition of Done|Acceptance(?: criteria)?)"
                       r"\b")


RESEARCH_POLICIES = ("required", "off")


def check_config(data: dict) -> str:
    """'' or why [triage] / [harness] max_concurrency is refused (config.check_triage)."""
    t = data["triage"]
    if t["research"] not in RESEARCH_POLICIES:
        return f"[triage] research = {t['research']!r}: one of {', '.join(RESEARCH_POLICIES)}"
    if not 2 <= t["fanout_min"] <= 100:
        return f"[triage] fanout_min = {t['fanout_min']}: must be 2-100"
    if not 0 <= t["prior_limit"] <= 20:
        return f"[triage] prior_limit = {t['prior_limit']}: must be 0-20"
    mc = data["harness"]["max_concurrency"]
    if not 0 <= mc <= 4096:
        return f"[harness] max_concurrency = {mc}: must be 0 (unknown) - 4096"
    return ""


@dataclass
class Tier:
    name: str
    why: str
    agents: int            # the agents (typed runs) to run at once: 0 inline, 1 agent/factory
    cap: int               # the most typed runs the endpoint's slots allow at once
    cap_source: str
    parts: int             # independent parts counted in the task
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    def line(self) -> str:
        n = f", {self.agents} at a time (cap {self.cap})" if self.name in ("fanout", "max") else ""
        return f"{self.name} ({self.why}{n})"


def cap_of(hcfg: dict) -> tuple:
    """(cap, source): how many typed runs may run at once on the configured endpoint."""
    per = max(1, int(hcfg.get("max_parallel") or 1))
    slots = int(hcfg.get("max_concurrency") or 0)
    if slots > 0:
        src = f"[harness] max_concurrency {slots}"
    else:
        slots = per
        src = (f"[harness] max_concurrency unset (the endpoint's slots are unknown), so "
               f"max_parallel {per}")
    n = max(1, slots // per)
    return n, f"{n} = {src} / {per} phase(s) per typed run ([harness] max_parallel)"


def scope_text(task: str) -> str:
    """The part of the task that names the work: everything before its DoD section (DoD rows and
    PROBE lines name checks, not parts)."""
    m = DOD_START.search(task)
    return task[:m.start()] if m else task


def parts_of(task: str) -> tuple:
    """(parts, signal): the independent parts the task names."""
    text = TAG.sub(" ", scope_text(task))
    items = len(LIST_ITEM.findall(text))
    paths = len({p.lower() for p in PATH.findall(text)})
    count = 0
    for m in COUNT.finditer(text):
        raw = m.group(1).lower()
        count = max(count, int(raw) if raw.isdigit() else NUMBERS[raw])
    best = max((items, "list items"), (paths, "file paths"), (count, "an explicit count"))
    return best[0], (f"{best[0]} {best[1]}" if best[0] else "no parts named")


def factory_fit(task: str, ttype: str, cat, decision_types) -> str:
    """'' when the task suits the factory, else why not."""
    if not ACCEPTANCE.search(task):
        return ("no mechanical acceptance (PROBE:/VERIFY_CMD: rows, a DoD section or 'until the "
                "tests pass'): an uncheckable goal never ends on its own")
    if cat.types[ttype].get("deliverable") != "build":
        return (f"[type:{ttype}] delivers a {cat.types[ttype].get('deliverable')}, not something "
                "the factory can ship and check")
    if ttype in (decision_types or ()):
        return f"[type:{ttype}] ships only by an owner decision ([ship] decision_types)"
    return ""


def keyword_type(task: str, cat) -> str:
    from konstant.gate.classify import keyword_hit
    t, _w = keyword_hit(TAG.sub(" ", task), cat)
    return t or "code"


def decide(task: str, ttype, why: str, cat, cfg_data: dict, bound: bool = False) -> tuple:
    """(type, why, Tier). `ttype` None = the classifier said small. `bound`: the run works on one
    board job (a job is one unit: never factory)."""
    tri = cfg_data.get("triage") or {}
    fan_min = max(2, int(tri.get("fanout_min", 3)))
    cap, src = cap_of(cfg_data["harness"])
    parts, signal = parts_of(task)
    m = TAG.search(task)
    tag = m.group(1).lower() if m else ""
    note = ""
    if tag and tag not in TIERS:
        note = f"[tier:{tag}] is not a tier ({', '.join(TIERS)}); the rules decided"
        tag = ""
    if tag:
        if tag == "inline":
            return None, "tier-tag", Tier("inline", "tag", 0, cap, src, parts, note)
        if ttype is None:
            ttype, why = keyword_type(task, cat), "tier-tag"
        if tag == "factory" and bound:
            return ttype, why, Tier("agent", "tag factory on a bound job: a job is one unit; "
                                    "file a goal for the factory", 1, cap, src, parts, note)
        n = {"agent": 1, "factory": 1, "max": cap,
             "fanout": min(max(parts, 2), cap)}[tag]
        return ttype, why, Tier(tag, "tag", n, cap, src, parts, note)
    if ttype is None:
        return None, why, Tier("inline", why, 0, cap, src, parts, note)
    unfit = ""
    if LONG_RUNNING.search(task) and not bound:
        unfit = factory_fit(task, ttype, cat, (cfg_data.get("ship") or {}).get("decision_types"))
        if not unfit:
            return ttype, why, Tier("factory", "long-running goal with a mechanical acceptance",
                                    1, cap, src, parts, note)
        note = "; ".join(x for x in (note, f"factory-unsuitable: {unfit}") if x)
    h = HUGE.search(scope_text(task))
    if h:
        return ttype, why, Tier("max", f"whole-scope: {h.group(0).strip()!r}", cap, cap, src,
                                parts, note)
    if parts > cap and parts >= fan_min:
        return ttype, why, Tier("max", f"{signal}, more than the cap", cap, cap, src, parts, note)
    if parts >= fan_min:
        return ttype, why, Tier("fanout", signal, min(parts, cap), cap, src, parts, note)
    return ttype, why, Tier("agent", signal if parts else "one deliverable", 1, cap, src, parts,
                            note)
