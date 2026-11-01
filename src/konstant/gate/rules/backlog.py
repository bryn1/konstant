"""Rule `backlog` (docs/LEVEL5.md 4.2): an `intake` run's backlog passes the deterministic filing
rules (factory/backlog.py) before the run can be MET, so a weak DoD sends the planner back with the
reasons instead of reaching the board. A missing SHIP line for a job is the DoD reviewer's to fix.
Only `intake` runs; unexcusable (DECLINED never waives what the filing will refuse anyway)."""
from __future__ import annotations

from pathlib import Path

from konstant.gate.rules.common import Finding, Run


def roots_for(cfg, target) -> object:
    from konstant.verify.verifier import build_roots
    paths = [{"path": str(cfg.home / "projects")}] + ([{"path": str(target)}] if target else [])
    return build_roots(cfg, paths)


def goal_limits(cfg, slug: str) -> dict:
    """max_jobs etc. from the factory's own copy of the goal (never from the run record)."""
    from konstant.factory import goal as goal_mod
    p = Path(cfg.home) / "var" / "factory" / "goals" / f"{slug}.toml"
    try:
        spec = goal_mod.parse(p.read_text(encoding="utf-8"), cfg.data["factory"]["defaults"],
                              cfg.data["holdout"]["min_per_job"])
    except (OSError, goal_mod.GoalError):
        return {}
    return spec["limits"]


def check(run: Run) -> list:
    if run.rec.get("type") != "intake":
        return []
    from konstant import config
    from konstant.factory import backlog
    cfg = config.load(Path(run.workspace))
    slug = str(run.rec.get("goal") or "")
    limits = goal_limits(cfg, slug) if slug else {}
    if slug and not limits:
        return [Finding("backlog", f"goal {slug}: the factory's copy var/factory/goals/{slug}.toml "
                        "is missing or invalid", "none")]
    reasons, _jobs = backlog.lint(run.out, run.catalog, roots_for(cfg, run.rec.get("target")),
                                  limits.get("max_jobs", 0))
    out = []
    for r in reasons:
        owner = f"verifier:{backlog.VERDICT}" if backlog.VERDICT in r else "producer"
        out.append(Finding("backlog", r, owner))
    return out
