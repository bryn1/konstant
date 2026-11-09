"""The factory on the board (docs/LEVEL5.md 6): its view (read routes, any valid token) and the
factory identity's bookkeeping writes. No route here serves a brief, an acceptance, evidence or
holdout content: holdouts appear as counts and states only (6.4).

GET  /api/factory/status            the loop (running|draining|stale|stopped, its heartbeat),
                                    halted or not, shipping, goals with counts, open escalations,
                                    the last events
GET  /api/factory/goals[/{ref}]     per goal: budget (used and limit per kind), jobs by state with
                                    attempts left, ships, escalations, the last tick
GET  /api/factory/escalations       ?open=true for the unacknowledged ones
POST /api/factory/escalations       (factory) register one: one OPEN row per (goal, job, kind);
                                    a repeat answers the open row with `new: false`
POST /api/factory/escalations/{id}/delivered   (factory) where it went
POST /api/factory/escalations/{id}/ack         (owner) acknowledged: the next one is told again,
                                    and the limit that raised it gets a fresh window
POST /api/factory/ledger            (factory) one charge; idempotent by `ref`
POST /api/factory/jobs/{ref}/exhausted  (factory) a job that used its max_attempts (counted from
                                    the board's own ledger) -> blocked
POST /api/factory/goals/{ref}/done  (factory) every job of the goal settled -> goal done
GET/POST /api/factory/halt          the factory halt (notifier failure, internal error): halt by
                                    the factory or the owner, resume by the owner only
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from konstant.board import db, tree
from konstant.board.api.deps import Actor, add_trail, load_job, reader, set_status, writer
from konstant.board.api.goals import goal_spec, load_goal
from konstant.board.redact import redact
from konstant.factory import budget, notify

router = APIRouter()


def _factory_only(actor: Actor, what: str) -> None:
    from konstant.board.api.ships import _is_factory
    if not _is_factory(actor):
        raise HTTPException(403, f"{what} is the factory identity's step (this token is "
                                 f"{actor.label}, role {actor.role})")


class EscIn(BaseModel):
    goal: str = ""
    job: int | None = None
    kind: str
    reason: str
    event_id: int | None = None


class ToIn(BaseModel):
    to: str = ""


class LedgerIn(BaseModel):
    goal: str = ""
    job: int | None = None
    kind: str
    amount: float
    ref: str


class ReasonIn(BaseModel):
    reason: str = ""


class HaltIn(BaseModel):
    action: str
    reason: str = ""


def halted(conn) -> dict | None:
    row = conn.execute("SELECT * FROM factory_log ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row and row["state"] == "halted" else None


def _goal_id(conn, slug: str):
    return load_goal(conn, slug)["id"] if slug else None


def esc_rows(conn, where: str = "", args=()) -> list:
    rows = conn.execute("SELECT e.*, g.slug AS goal FROM escalations e LEFT JOIN goals g ON "
                        f"g.id = e.goal_id {where} ORDER BY e.id", args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["display_id"] = tree.display_id(conn, r["job_id"]) if r["job_id"] else None
        d["open"] = r["acked_by"] is None
        out.append(d)
    return out


@router.post("/api/factory/escalations")
def add_escalation(body: EscIn, request: Request, actor: Actor = Depends(writer)):
    _factory_only(actor, "an escalation")
    if body.kind not in notify.ESCALATIONS:
        raise HTTPException(422, f"kind is one of {', '.join(notify.ESCALATIONS)}")
    with db.transaction(request.app.state.db_path) as conn:
        gid = _goal_id(conn, body.goal)
        jid = load_job(conn, str(body.job))["id"] if body.job is not None else None
        row = conn.execute("SELECT id FROM escalations WHERE coalesce(goal_id,0)=? AND "
                           "coalesce(job_id,0)=? AND kind=? AND acked_by IS NULL",
                           (gid or 0, jid or 0, body.kind)).fetchone()
        if row:
            return {"id": row["id"], "new": False}
        eid = conn.execute("INSERT INTO escalations (goal_id, job_id, kind, reason, event_id) "
                           "VALUES (?,?,?,?,?)", (gid, jid, body.kind,
                                                  redact(body.reason)[:1000],
                                                  body.event_id)).lastrowid
        return {"id": eid, "new": True}


@router.post("/api/factory/escalations/{eid}/delivered")
def delivered(eid: int, body: ToIn, request: Request, actor: Actor = Depends(writer)):
    _factory_only(actor, "marking a delivery")
    with db.transaction(request.app.state.db_path) as conn:
        conn.execute("UPDATE escalations SET delivered_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'), "
                     "delivered_to=? WHERE id=? AND delivered_at IS NULL", (body.to[:200], eid))
    return {"id": eid}


@router.post("/api/factory/escalations/{eid}/ack")
def ack(eid: int, request: Request, actor: Actor = Depends(writer)):
    if actor.role != "owner":
        raise HTTPException(403, "only the owner acknowledges an escalation")
    with db.transaction(request.app.state.db_path) as conn:
        row = conn.execute("SELECT * FROM escalations WHERE id=?", (eid,)).fetchone()
        if row is None:
            raise HTTPException(404, f"escalation {eid} not found")
        if row["acked_by"] is not None:
            raise HTTPException(409, f"escalation {eid} was acknowledged already")
        conn.execute("UPDATE escalations SET acked_by=?, acked_at=strftime('%Y-%m-%dT%H:%M:%SZ',"
                     "'now') WHERE id=?", (actor.label, eid))
        return esc_rows(conn, "WHERE e.id=?", (eid,))[0]


@router.get("/api/factory/escalations")
def list_escalations(request: Request, open: bool = False, goal: str = "",
                     actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        where, args = [], []
        if open:
            where.append("e.acked_by IS NULL")
        if goal:
            where.append("e.goal_id=?")
            args.append(load_goal(conn, goal)["id"])
        return {"escalations": esc_rows(conn, ("WHERE " + " AND ".join(where)) if where else "",
                                         args)}


@router.post("/api/factory/ledger")
def charge(body: LedgerIn, request: Request, actor: Actor = Depends(writer)):
    _factory_only(actor, "a budget charge")
    if body.kind not in budget.KINDS or body.amount < 0 or not body.ref.strip():
        raise HTTPException(422, f"kind one of {', '.join(budget.KINDS)}, amount >= 0, a ref")
    with db.transaction(request.app.state.db_path) as conn:
        old = conn.execute("SELECT id FROM budget_ledger WHERE ref=?", (body.ref,)).fetchone()
        if old:
            return {"id": old["id"], "new": False}
        gid = _goal_id(conn, body.goal)
        job = load_job(conn, str(body.job)) if body.job is not None else None
        lid = conn.execute("INSERT INTO budget_ledger (goal_id, job_id, kind, amount, ref, actor) "
                           "VALUES (?,?,?,?,?,?)", (gid, job["id"] if job else None, body.kind,
                                                    body.amount, body.ref[:300],
                                                    actor.label)).lastrowid
        return {"id": lid, "new": True}


@router.post("/api/factory/jobs/{ref}/exhausted")
def exhausted(ref: str, body: ReasonIn, request: Request, actor: Actor = Depends(writer)):
    """The budget stop of ONE job (6.2): queued or claimed -> blocked, only when the board's own
    ledger shows the job's max_attempts used (the factory cannot block a job on its own say)."""
    _factory_only(actor, "a job's budget stop")
    with db.transaction(request.app.state.db_path) as conn:
        job = load_job(conn, ref)
        cap, used = budget.max_attempts(job), budget.attempts(conn, job["id"])
        if not cap or used < cap:
            raise HTTPException(409, f"job {job['id']} used {used} of {cap or '?'} attempts")
        if job["status"] not in ("queued", "claimed"):
            raise HTTPException(409, f"job {job['id']} is {job['status']}")
        why = f"blocked: {used} of {cap} attempts used (max_attempts)" + (
            f": {redact(body.reason)[:300]}" if body.reason else "")
        set_status(conn, job["id"], "blocked")
        add_trail(conn, job["id"], actor, "budget", why, {"attempts": used, "max_attempts": cap})
        add_trail(conn, job["id"], actor, "status", why)
        return {"job": job["id"], "status": "blocked", "attempts": used}


def settled(conn, job) -> bool:
    if job["status"] == "cancelled":
        return True
    s = conn.execute("SELECT state, post_json, follow_up_id FROM ships WHERE job_id=? AND "
                     "state <> 'failed' ORDER BY id DESC LIMIT 1", (job["id"],)).fetchone()
    return bool(s) and ((s["state"] == "shipped" and s["post_json"] is not None)
                        or (s["state"] == "rolled_back" and s["follow_up_id"] is not None))


@router.post("/api/factory/goals/{ref}/done")
def goal_done(ref: str, request: Request, actor: Actor = Depends(writer)):
    _factory_only(actor, "marking a goal done")
    with db.transaction(request.app.state.db_path) as conn:
        g = load_goal(conn, ref)
        jobs = conn.execute("SELECT * FROM jobs WHERE goal_id=?", (g["id"],)).fetchall()
        open_ = [j["id"] for j in jobs if not settled(conn, j)]
        if g["status"] != "active" or g["intake"] != "filed" or not jobs or open_:
            raise HTTPException(409, f"goal {g['slug']} is {g['status']} (intake {g['intake']});"
                                     f" jobs not shipped: {open_ or 'none filed'}")
        conn.execute("UPDATE goals SET status='done', updated_at=strftime('%Y-%m-%dT%H:%M:%SZ',"
                     "'now') WHERE id=?", (g["id"],))
        return {"goal": g["slug"], "status": "done"}


@router.get("/api/factory/halt")
def get_halt(request: Request, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        h = halted(conn)
    return {"halted": bool(h), "since": h["at"] if h else None, "reason": h["reason"] if h else None}


@router.post("/api/factory/halt")
def set_halt(body: HaltIn, request: Request, actor: Actor = Depends(writer)):
    from konstant.board.api.ships import _is_factory
    if body.action == "resume" and actor.role != "owner":
        raise HTTPException(403, "only the owner resumes a halted factory")
    if body.action == "halt" and actor.role != "owner" and not _is_factory(actor):
        raise HTTPException(403, "the factory is halted by the owner or the factory identity")
    if body.action not in ("halt", "resume"):
        raise HTTPException(422, "action is halt or resume")
    with db.transaction(request.app.state.db_path) as conn:
        if (halted(conn) is not None) == (body.action == "halt"):
            raise HTTPException(409, f"the factory is already "
                                     f"{'halted' if body.action == 'halt' else 'running'}")
        conn.execute("INSERT INTO factory_log (state, reason, actor) VALUES (?,?,?)",
                     ("halted" if body.action == "halt" else "resumed",
                      redact(body.reason or body.action)[:500], actor.label))
    return {"halted": body.action == "halt"}


# --- the view ------------------------------------------------------------------------------------

def goal_view(conn, g) -> dict:
    spec = goal_spec(g)
    b = budget.goal_budget(conn, g, spec)
    jobs, by_state = [], {}
    for j in conn.execute("SELECT * FROM jobs WHERE goal_id=? ORDER BY id", (g["id"],)):
        cap, used = budget.max_attempts(j), budget.attempts(conn, j["id"])
        ship = conn.execute("SELECT id, state FROM ships WHERE job_id=? ORDER BY id DESC LIMIT 1",
                            (j["id"],)).fetchone()
        sealed = conn.execute("SELECT count(*) FROM holdouts WHERE job_id=? AND state='sealed'",
                              (j["id"],)).fetchone()[0]
        jobs.append({"id": j["id"], "display_id": tree.display_id(conn, j["id"]),
                     "title": j["title"], "type": j["type"], "status": j["status"],
                     "attempts": used, "max_attempts": cap, "attempts_left": max(0, cap - used),
                     "holdouts_sealed": sealed, "ship": dict(ship) if ship else None})
        by_state[j["status"]] = by_state.get(j["status"], 0) + 1
    ships = [dict(r) for r in conn.execute(
        "SELECT id, job_id, target, branch, state, commit_sha, tip_sha, rollback_sha, created_at, "
        "updated_at FROM ships WHERE goal_id=? ORDER BY id", (g["id"],))]
    return {"goal": g["slug"], "status": g["status"], "intake": g["intake"], "source": g["source"],
            "budget": b, "exhausted": budget.exhausted(b), "jobs": jobs, "jobs_by_state": by_state,
            "ships": ships, "escalations": esc_rows(conn, "WHERE e.goal_id=?", (g["id"],))}


def loop_state(cfg) -> dict:
    from konstant.factory import proc
    st = proc.state(cfg.home, cfg.data["factory"]["tick_s"])
    hb = st["heartbeat"] or {}
    return {"state": st["state"], "pid": st["pid"], "stop": st["stop"],
            "last_tick": hb.get("at"), "tick": hb.get("tick"), "steps": hb.get("steps") or [],
            "ready": hb.get("ready"), "progress_at": hb.get("progress_at")}


@router.get("/api/factory/goals")
def factory_goals(request: Request, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        rows = conn.execute("SELECT * FROM goals WHERE status <> 'withdrawn' ORDER BY id")
        return {"goals": [goal_view(conn, g) for g in rows.fetchall()],
                "last_tick": loop_state(request.app.state.cfg)["last_tick"]}


@router.get("/api/factory/goals/{ref}")
def factory_goal(ref: str, request: Request, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        out = goal_view(conn, load_goal(conn, ref))
    out["last_tick"] = loop_state(request.app.state.cfg)["last_tick"]
    return out


@router.get("/api/factory/status")
def factory_status(request: Request, actor: Actor = Depends(reader)):
    from konstant.board.api.ships import halted as ship_halt
    cfg = request.app.state.cfg
    with db.reading(request.app.state.db_path) as conn:
        h, sh = halted(conn), ship_halt(conn)
        goals = [{"goal": g["slug"], "status": g["status"], "intake": g["intake"]}
                 for g in conn.execute("SELECT slug, status, intake FROM goals WHERE status <> "
                                       "'withdrawn' ORDER BY id")]
        ships: dict = {}
        for r in conn.execute("SELECT state, count(*) n FROM ships GROUP BY state"):
            ships[r["state"]] = r["n"]
        open_ = conn.execute("SELECT count(*) FROM escalations WHERE acked_by IS NULL").fetchone()[0]
    events = [{k: e.get(k) for k in ("id", "event", "kind", "goal", "display_id", "reason", "at",
                                     "suppressed")}
              for e in notify.read_events(cfg.home)[-20:]]
    return {"factory": loop_state(cfg), "halted": bool(h),
            "halt": {"since": h["at"], "reason": h["reason"]} if h else None,
            "shipping": "halted" if sh else "open", "ships": ships, "goals": goals,
            "open_escalations": open_, "spooled": len(notify.spooled(cfg.home)),
            "events": events}
