"""Goal files (docs/LEVEL5.md 4.1): the goal and its limits, nothing else.

A goal file is TOML with four tables: `[goal]` (id, project, text), `[limits]` (only
`max_attempts` is required, owner decision Q5; every other limit is optional and 0 / absent means
not limited), `[ship]` (target, branch, post_probes and the target's own keys; consumed by the
ship wave) and `[holdout]` (author agent|owner, min_per_job). What a file does not name comes from
the workspace's `[factory] defaults` (and `[holdout] min_per_job`). Validation is deterministic and
fails closed: an unknown table or key, a wrong type or an out-of-range value refuses the whole
file with one `goal: ...` reason per problem.

The board validates a goal with `parse()` when it is filed (`POST /api/goals`), copies the bytes
it was given into var/factory/goals/<id>.toml (machinery: no phase writes it) and records
sha256(bytes) as the goal's immutable `spec_sha256`. The factory reads only that copy.
"""
from __future__ import annotations

import re

try:  # Python >= 3.11
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as _toml

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
TARGETS = ("github", "branch", "apply", "command")
AUTHORS = ("agent", "owner")
INT_LIMITS = ("max_task_runs", "max_jobs", "max_rollbacks", "max_tokens")
DEFAULTS = {"max_attempts": 3, "wall_clock": "0", "max_task_runs": 0, "max_jobs": 0,
            "max_rollbacks": 0, "max_tokens": 0, "max_cost_usd": 0,
            "ship_target": "branch", "ship_branch": "main", "holdout_author": "agent"}
LIMIT_KEYS = ("max_attempts", "wall_clock", *INT_LIMITS, "max_cost_usd")
SHIP_KEYS = ("target", "branch", "post_probes", "github_repo", "apply_dir", "ship_cmd",
             "rollback_cmd")
TABLES = {"goal": ("id", "project", "text"), "limits": LIMIT_KEYS, "ship": SHIP_KEYS,
          "holdout": ("author", "min_per_job")}
_WALL = re.compile(r"(\d+)([smhd]?)")
MAX_TEXT = 8000


class GoalError(Exception):
    """A goal file the factory refuses; .reasons holds every `goal: ...` line."""

    def __init__(self, reasons):
        reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def wall_seconds(text: str) -> int | None:
    """"0" -> 0, "45m" -> 2700, "4h", "2d", "90s", a bare number = seconds; None if malformed."""
    m = _WALL.fullmatch(str(text).strip())
    if not m:
        return None
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def check_limits(limits: dict, where: str = "limits") -> list:
    out = []
    if not _int(limits.get("max_attempts")) or limits["max_attempts"] < 1:
        out.append(f"goal: {where}.max_attempts must be >= 1 (the one required limit: attempts "
                   "per job before it is BLOCKED)")
    if wall_seconds(limits.get("wall_clock", "0")) is None:
        out.append(f"goal: {where}.wall_clock must look like \"0\", \"90m\", \"4h\" or \"2d\"")
    for k in INT_LIMITS:
        if not _int(limits.get(k, 0)) or limits.get(k, 0) < 0:
            out.append(f"goal: {where}.{k} must be an integer >= 0 (0 = not limited)")
    cost = limits.get("max_cost_usd", 0)
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
        out.append(f"goal: {where}.max_cost_usd must be a number >= 0 (0 = not limited)")
    return out


def check_defaults(defaults: dict) -> None:
    """[factory] defaults of konstant.toml (merged over DEFAULTS); GoalError when malformed."""
    unknown = sorted(set(defaults) - set(DEFAULTS))
    if unknown:
        raise GoalError(f"unknown key(s) {', '.join(unknown)} (known: {', '.join(DEFAULTS)})")
    d = effective_defaults(defaults)
    bad = check_limits(d, "defaults")
    if d["ship_target"] not in TARGETS:
        bad.append(f"ship_target must be one of {', '.join(TARGETS)}")
    if d["holdout_author"] not in AUTHORS:
        bad.append(f"holdout_author must be one of {', '.join(AUTHORS)}")
    if not isinstance(d["ship_branch"], str) or not d["ship_branch"].strip():
        bad.append("ship_branch must be a branch name")
    if bad:
        raise GoalError(bad)


def effective_defaults(defaults: dict | None) -> dict:
    return {**DEFAULTS, **(defaults or {})}


def parse(text: str, defaults: dict | None = None, min_per_job: int = 2) -> dict:
    """The validated, normalised spec of a goal file (defaults applied). GoalError otherwise."""
    try:
        raw = _toml.loads(text)
    except _toml.TOMLDecodeError as exc:
        raise GoalError(f"goal: not valid TOML: {exc}") from None
    d = effective_defaults(defaults)
    reasons = []
    for table, value in raw.items():
        if table not in TABLES:
            reasons.append(f"goal: unknown table [{table}] (known: {', '.join(TABLES)})")
        elif not isinstance(value, dict):
            reasons.append(f"goal: [{table}] must be a table")
        else:
            reasons += [f"goal: unknown key {table}.{k}" for k in value if k not in TABLES[table]]
    if reasons:
        raise GoalError(reasons)
    g = raw.get("goal", {})
    gid, project, gtext = g.get("id"), g.get("project"), g.get("text")
    if not isinstance(gid, str) or not SLUG.fullmatch(gid):
        reasons.append("goal: goal.id must be a slug (a-z, 0-9, '-', up to 40 characters)")
    if not isinstance(project, str) or not project.strip():
        reasons.append("goal: goal.project must name an existing konstant project")
    if not isinstance(gtext, str) or not gtext.strip():
        reasons.append("goal: goal.text must say what the owner wants (non-empty)")
    elif len(gtext) > MAX_TEXT:
        reasons.append(f"goal: goal.text is over {MAX_TEXT} characters")
    limits = {k: d[k] for k in LIMIT_KEYS}
    limits.update(raw.get("limits", {}))
    reasons += check_limits(limits)
    ship = {"target": d["ship_target"], "branch": d["ship_branch"], "post_probes": []}
    ship.update(raw.get("ship", {}))
    if ship["target"] not in TARGETS:
        reasons.append(f"goal: ship.target must be one of {', '.join(TARGETS)}")
    for k in SHIP_KEYS:
        if k == "post_probes":
            v = ship[k]
            if not isinstance(v, list) or not all(isinstance(p, str) and
                                                  p.lstrip().startswith("PROBE:") for p in v):
                reasons.append("goal: ship.post_probes must be a list of `PROBE: ...` lines")
        elif k in ship and not isinstance(ship[k], str):
            reasons.append(f"goal: ship.{k} must be a string")
    hold = {"author": d["holdout_author"], "min_per_job": min_per_job}
    hold.update(raw.get("holdout", {}))
    if hold["author"] not in AUTHORS:
        reasons.append(f"goal: holdout.author must be one of {', '.join(AUTHORS)}")
    if not _int(hold["min_per_job"]) or hold["min_per_job"] < 1:
        reasons.append("goal: holdout.min_per_job must be an integer >= 1")
    if reasons:
        raise GoalError(reasons)
    return {"goal": {"id": gid, "project": project.strip(), "text": gtext.strip()},
            "limits": limits, "ship": ship, "holdout": hold}


def job_budget(spec: dict) -> dict:
    """A job's share of its goal's limits (docs/LEVEL5.md 6.2): its own max_attempts, and the
    goal-wide limits that are set (they are charged to the goal, so a job carries them as the
    ceiling it runs under, never as a per-job grant)."""
    lim = spec["limits"]
    goal_wide = {k: lim[k] for k in LIMIT_KEYS if k != "max_attempts"
                 and lim[k] not in (0, "0", 0.0)}
    return {"max_attempts": lim["max_attempts"], "goal_limits": goal_wide}


def summary(spec: dict) -> str:
    """One line: project, goal text (shortened), the limits that are set."""
    lim = spec["limits"]
    set_ = [f"{k} {lim[k]}" for k in LIMIT_KEYS if k == "max_attempts" or lim[k] not in
            (0, "0", 0.0)]
    text = " ".join(spec["goal"]["text"].split())
    text = text if len(text) <= 120 else text[:117] + "..."
    return f"project {spec['goal']['project']}: \"{text}\" ({', '.join(set_)})"
