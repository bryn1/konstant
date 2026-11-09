"""Budgets (docs/LEVEL5.md 6.2): what a goal may spend, what it spent, and whether it may go on.

Owner decision Q5: `max_attempts` (task runs per job, default 3) is the only required limit; wall
clock, total task runs, tokens and cost are optional and unlimited when absent or 0. Spending is
written by code into the board's append-only `budget_ledger` (board/api/factory.py):

  attempts, task_runs   charged BEFORE a job's task run starts (a run killed with the host still
                        counts; nothing is charged twice: each charge has a unique ref)
  wall_s, phases        from the finished run's phase manifests (phases/*.json `seconds`)
  tokens, cost          from `Adapter.usage(log)`, only for an adapter that measures them
  rollbacks             counted from `ships` (the ship step turns the rollback after
                        `max_rollbacks` into BLOCKED itself)

A token or cost limit on a harness that cannot measure it is refused BEFORE the start
(`budget max_cost_usd cannot be measured on harness command`): konstant does not guess spending.
An acknowledged escalation opens a fresh window for the limit that raised it: a goal's budget
counts the ledger after its last acknowledged BUDGET_STOP, a job's attempts after its last
acknowledged BLOCKED (so `factory ack` + `goal resume` / `job reopen` is how the owner grants more).
"""
from __future__ import annotations

import json
from pathlib import Path

# goal limit -> ledger kind; only these stop a goal (max_jobs is the filing's, max_rollbacks the
# ship step's own rule)
STOPS = {"max_task_runs": "task_runs", "wall_clock": "wall_s", "max_tokens": "tokens",
         "max_cost_usd": "cost"}
MEASURED = ("max_tokens", "max_cost_usd")
KINDS = ("wall_s", "attempts", "task_runs", "phases", "tokens", "cost", "rollbacks")


def limit_of(spec: dict, key: str) -> float:
    from konstant.factory.goal import wall_seconds
    v = spec["limits"].get(key, 0)
    if key == "wall_clock":
        return float(wall_seconds(str(v)) or 0)
    return float(v or 0)


def harness_names(hcfg: dict, override: str | None = None) -> list:
    from konstant import harnesses
    if override:
        return [override if override in harnesses.ADAPTERS else "command"]
    return harnesses.configured(hcfg)


def unmeasurable(cfg, spec: dict, override: str | None = None) -> str | None:
    """Why this goal's budget cannot be kept on the configured harnesses (None: it can)."""
    from konstant import harnesses
    hcfg = cfg.data["harness"]
    for key in MEASURED:
        if limit_of(spec, key) <= 0:
            continue
        for name in harness_names(hcfg, override):
            if not harnesses.adapter(name).measures(hcfg):
                return f"budget {key} cannot be measured on harness {name}"
    return None


# --- the board side: what was spent (SQL over the board's own records) ------------------------

def _since(conn, goal_id, job_id, kind: str) -> str:
    """The acked_at of the newest acknowledged escalation of `kind` for this goal / job ('' when
    none): the start of the current window."""
    if job_id is None:
        row = conn.execute("SELECT max(acked_at) FROM escalations WHERE goal_id=? AND job_id IS "
                           "NULL AND kind=? AND acked_by IS NOT NULL", (goal_id, kind)).fetchone()
    else:
        row = conn.execute("SELECT max(acked_at) FROM escalations WHERE job_id=? AND kind=? AND "
                           "acked_by IS NOT NULL", (job_id, kind)).fetchone()
    return row[0] or ""


def spent(conn, goal_id: int) -> dict:
    """{kind: amount} charged to the goal in its current window."""
    since = _since(conn, goal_id, None, "BUDGET_STOP")
    out = {k: 0.0 for k in KINDS}
    for r in conn.execute("SELECT kind, sum(amount) FROM budget_ledger WHERE goal_id=? AND at>=? "
                          "GROUP BY kind", (goal_id, since)).fetchall():
        out[r[0]] = float(r[1] or 0)
    out["rollbacks"] = float(conn.execute(
        "SELECT count(*) FROM ships WHERE goal_id=? AND state='rolled_back'", (goal_id,))
        .fetchone()[0])
    return out


def attempts(conn, job_id: int) -> int:
    since = _since(conn, None, job_id, "BLOCKED")
    return int(conn.execute("SELECT count(*) FROM budget_ledger WHERE job_id=? AND "
                            "kind='attempts' AND at>=?", (job_id, since)).fetchone()[0])


def max_attempts(job_row) -> int:
    raw = job_row["budget_json"]
    try:
        return int(json.loads(raw)["max_attempts"]) if raw else 0
    except (ValueError, KeyError, TypeError):
        return 0


def goal_budget(conn, goal_row, spec: dict) -> dict:
    """{limit key: {kind, used, limit}} for every limit (0 = not limited) plus max_attempts."""
    used = spent(conn, goal_row["id"])
    out = {"max_attempts": {"kind": "attempts", "per": "job",
                            "limit": spec["limits"]["max_attempts"]}}
    for key, kind in (*STOPS.items(), ("max_rollbacks", "rollbacks")):
        out[key] = {"kind": kind, "used": used[kind], "limit": limit_of(spec, key)}
    out["max_jobs"] = {"kind": "jobs", "limit": limit_of(spec, "max_jobs"), "used": float(
        conn.execute("SELECT count(*) FROM jobs WHERE goal_id=?", (goal_row["id"],))
        .fetchone()[0])}
    out["phases"] = {"kind": "phases", "used": used["phases"], "limit": 0}
    return out


def exhausted(budget: dict) -> list:
    """One reason per goal limit that is reached (used >= limit > 0)."""
    out = []
    for key in STOPS:
        b = budget.get(key) or {}
        if b.get("limit") and b.get("used", 0) >= b["limit"]:
            out.append(f"{key} {fmt(b['limit'])} reached ({fmt(b['used'])} used)")
    return out


def fmt(v) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


# --- the factory side: what one finished run cost ----------------------------------------------

def run_charges(cfg, run_dir: Path) -> dict:
    """{kind: amount} measured from a run's phase manifests: wall_s and phases always; tokens and
    cost only from adapters that measure them (Adapter.usage on each phase log)."""
    from konstant import harnesses
    hcfg = cfg.data["harness"]
    out = {"wall_s": 0.0, "phases": 0.0}
    tokens = cost = None
    for f in sorted((Path(run_dir) / "phases").glob("*.json")):
        try:
            m = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        out["wall_s"] += float(m.get("seconds") or 0)
        out["phases"] += 1
        name = m.get("harness") or "command"
        ad = harnesses.ADAPTERS.get(name)
        if ad is None or not ad().measures(hcfg) or not m.get("log"):
            continue
        u = ad().usage(Path(m["log"]))
        if u:
            tokens = (tokens or 0) + int(u.get("tokens") or 0)
            cost = (cost or 0.0) + float(u.get("cost_usd") or 0)
    if tokens is not None:
        out["tokens"] = float(tokens)
    if cost is not None:
        out["cost"] = cost
    return out
