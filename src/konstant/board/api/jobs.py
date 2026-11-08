"""Filing and reading jobs: add, list, show, search."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from konstant.board import db, dod, transitions, tree
from konstant.board.api import holdouts
from konstant.board.api.deps import (Actor, add_trail, load_job, reader, refuse, serialize,
                                     trail_rows, writer)
from konstant.board.redact import redact
from konstant.board.transitions import Refused

router = APIRouter()
TYPE_TAG = re.compile(r"\[type:([a-z_]+)\]")


MAX_BRIEF = 256 * 1024
LIST_DROP = ("brief", "acceptance", "evidence")   # lists stay small; `job show` has everything


def _listed(conn, row) -> dict:
    out = serialize(conn, row)
    for k in LIST_DROP:
        out.pop(k, None)
    return out


class JobIn(BaseModel):
    title: str = Field(max_length=500)
    project: str
    brief: str = Field(max_length=MAX_BRIEF)
    type: str = ""
    parent: str = ""
    priority: int = 2
    after: str = ""
    approval: bool = False
    holdout_required: bool = False      # claimable only with sealed holdouts (LEVEL5 3.2)
    goal: str = ""                      # a goal job, filed by the planner identity (LEVEL5 4.2)


GOAL_FILERS = ("planner",)


def goal_fields(conn, st, body: JobIn, actor: Actor, proj) -> dict:
    """A goal job (docs/LEVEL5.md 4.2 step 3): only the planner identity files it, only while the
    factory holds the goal's intake at `filing`, only under the goal's own project, within its
    max_jobs; it always waits for approval and for sealed holdouts. Its budget (its share of the
    goal's limits) and its ship mode (`decision` for a type in [ship] decision_types, owner
    decision Q4) are computed HERE, never taken from the caller."""
    from konstant.board.api.goals import goal_spec, load_goal
    from konstant.board.policy import role_of
    from konstant.factory.goal import job_budget
    if actor.label not in GOAL_FILERS or role_of(actor.label) != actor.role:
        raise HTTPException(403, f"goal jobs are filed by the {', '.join(GOAL_FILERS)} identity "
                                 f"(this token is {actor.label})")
    g = load_goal(conn, body.goal)
    if g["status"] != "active" or g["intake"] != "filing":
        raise HTTPException(409, f"goal {g['slug']} is {g['status']} with intake {g['intake']}: "
                                 "its jobs are filed only while the factory files its intake")
    if g["project_id"] != proj["id"]:
        raise HTTPException(409, f"goal {g['slug']}'s jobs are filed under its own project, not "
                                 f"{proj['slug']}")
    spec = goal_spec(g)
    cap = spec["limits"]["max_jobs"]
    have = conn.execute("SELECT count(*) FROM jobs WHERE goal_id=?", (g["id"],)).fetchone()[0]
    if cap and have >= cap:
        raise HTTPException(409, f"goal {g['slug']} has max_jobs = {cap} and {have} job(s)")
    decide = st.cfg.data["ship"]["decision_types"]
    return {"goal_id": g["id"], "budget_json": json.dumps(job_budget(spec), sort_keys=True),
            "ship_mode": "decision" if body.type in decide else "auto"}


@router.post("/api/jobs")
def add_job(body: JobIn, request: Request, actor: Actor = Depends(writer)):
    st = request.app.state
    try:
        transitions.check_role("add", actor.role, st.policy)
    except Refused as exc:
        refuse(exc)
    title = redact(body.title.strip())
    if not title:
        raise HTTPException(422, "a title is required")
    jtype = body.type.strip()
    if not jtype:
        tag = TYPE_TAG.search(title)
        jtype = tag.group(1) if tag else ""
    known = st.catalog.classifiable()               # a flag-only type (intake) is never a job
    if st.catalog.flag_only(jtype):
        raise HTTPException(422, f"type {jtype} runs only as `konstant {jtype}`, never as a "
                                 f"job; job types: {', '.join(known)}")
    if jtype not in known:
        what = f"unknown type {jtype!r}" if jtype else "a type is required (--type)"
        raise HTTPException(422, f"{what}; known types: {', '.join(known)}")
    body.type = jtype
    brief = redact(body.brief or "")
    acceptance = dod.extract_acceptance(brief)
    if not acceptance:
        raise HTTPException(422, "acceptance is required: the brief has no 'DoD:' (or "
                                 "'Acceptance:') line saying what must be TRUE for the job to "
                                 "count as done, in terms someone else can check")
    if not 0 <= body.priority <= 4:
        raise HTTPException(422, "priority must be 0..4")
    with db.transaction(st.db_path) as conn:
        proj = conn.execute("SELECT * FROM projects WHERE slug=?", (body.project,)).fetchone()
        if proj is None:
            raise HTTPException(404, f"project {body.project!r} not found")
        parent_id = proj["root_job_id"]
        if body.parent.strip():
            parent_id = tree.resolve_path(conn, body.parent)
            if parent_id is None:
                raise HTTPException(404, f"parent {body.parent} not found")
            prow = conn.execute("SELECT project_id FROM jobs WHERE id=?", (parent_id,)).fetchone()
            if prow["project_id"] != proj["id"]:
                raise HTTPException(409, f"parent {body.parent} belongs to another project")
        try:
            tree.check_new_child(conn, parent_id)
        except tree.TreeRefused as exc:
            refuse(exc)
        after_id = None
        if body.after.strip():
            after_id = tree.resolve_path(conn, body.after)
            if after_id is None:
                raise HTTPException(404, f"--after job {body.after} not found")
        gf = goal_fields(conn, st, body, actor, proj) if body.goal.strip() else {}
        if gf and after_id is not None:
            dep = conn.execute("SELECT goal_id FROM jobs WHERE id=?", (after_id,)).fetchone()
            if dep["goal_id"] != gf["goal_id"]:
                raise HTTPException(409, f"a goal job runs after another job of the same goal "
                                         f"(job {after_id} is not one)")
        approval = body.approval or bool(gf)          # a goal job always waits for approval
        holdout = body.holdout_required or bool(gf)   # ... and for its sealed holdouts
        status = "waiting_approval" if approval else "queued"
        job_id = conn.execute(
            "INSERT INTO jobs (project_id, parent_id, type, title, brief, acceptance, status, "
            "priority, requested_by, after_id, approval_required, holdout_required, goal_id, "
            "budget_json, ship_mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (proj["id"], parent_id, jtype, title, brief, acceptance, status, body.priority,
             actor.label, after_id, int(approval), int(holdout), gf.get("goal_id"),
             gf.get("budget_json"), gf.get("ship_mode"))).lastrowid
        add_trail(conn, job_id, actor, "status", f"filed as {status}"
                  + (f" for goal {body.goal.strip()}" if gf else ""))
        out = serialize(conn, conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    out["warnings"] = [f"DoD {cls}: {row!r} - {dod.ADVICE[cls]}" for cls, row in dod.lint(brief)]
    return out


@router.get("/api/jobs")
def list_jobs(request: Request, status: str = "", type: str = "", project: str = "",
              self_attested: bool = False, roots: bool = False, limit: int = 200,
              actor: Actor = Depends(reader)):
    q, args = "SELECT j.* FROM jobs j JOIN projects p ON p.id = j.project_id WHERE 1=1", []
    if status:
        states = [s for s in status.split(",") if s]
        q += " AND j.status IN (%s)" % ",".join("?" * len(states))
        args += states
    if type:
        q += " AND j.type=?"
        args.append(type)
    if project:
        q += " AND p.slug=?"
        args.append(project)
    if not roots:
        q += " AND j.parent_id IS NOT NULL"
    if self_attested:
        q += " AND json_extract(j.evidence_json, '$.self_attested') = 1"
    q += " ORDER BY j.id LIMIT ?"
    args.append(max(1, min(limit, 10000)))
    with db.reading(request.app.state.db_path) as conn:
        return {"jobs": [_listed(conn, r) for r in conn.execute(q, args).fetchall()]}


@router.get("/api/search")
def search_jobs(request: Request, q: str, open: bool = False, project: str = "",
                limit: int = 50, actor: Actor = Depends(reader)):
    words = [w for w in q.split() if w]
    if not words:
        raise HTTPException(422, "search needs at least one word")
    sql, args = ("SELECT j.* FROM jobs j JOIN projects p ON p.id = j.project_id "
                 "WHERE j.parent_id IS NOT NULL", [])
    for w in words:
        sql += " AND (j.title LIKE ? ESCAPE '\\' OR j.brief LIKE ? ESCAPE '\\')"
        pat = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args += [pat, pat]
    if open:
        sql += " AND j.status IN (%s)" % ",".join("?" * len(transitions.OPEN))
        args += list(transitions.OPEN)
    if project:
        sql += " AND p.slug=?"
        args.append(project)
    sql += " ORDER BY j.id DESC LIMIT ?"
    args.append(max(1, min(limit, 1000)))
    with db.reading(request.app.state.db_path) as conn:
        return {"jobs": [_listed(conn, r) for r in conn.execute(sql, args).fetchall()]}


@router.get("/api/jobs/{ref}")
def show_job(ref: str, request: Request, trail: bool = False, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        row = load_job(conn, ref)
        out = serialize(conn, row)
        out["verifications"] = []
        for v in conn.execute("SELECT id, round, actor, started_at, finished_at, verdict, "
                              "holdout_json FROM verifications WHERE job_id=? ORDER BY id",
                              (row["id"],)).fetchall():
            d = dict(v)
            raw = d.pop("holdout_json")
            if raw:                      # ids, pass/fail, timings: never content (LEVEL5 3.6)
                d["holdouts"] = json.loads(raw)
            out["verifications"].append(d)
        out["holdouts"] = holdouts.listing(conn, row["id"])
        from konstant.board.api import triage
        out["intake_cards"] = triage.listing(conn, row["id"])
        out["runs"] = [dict(r) for r in conn.execute(
            "SELECT * FROM runs WHERE job_id=? ORDER BY id", (row["id"],)).fetchall()]
        if trail:
            out["trail"] = trail_rows(conn, row["id"])
        return out


class RunIn(BaseModel):
    run_dir: str
    type: str
    started_at: str
    finished_at: str = ""
    result: str = ""


@router.post("/api/jobs/{ref}/runs")
def add_run(ref: str, body: RunIn, request: Request, actor: Actor = Depends(writer)):
    """Link a task run (its run dir and DoD result) to a job: the `runs` table (DESIGN §4.1)."""
    if body.result and body.result not in ("MET", "UNMET", "BLOCKED", "ERROR"):
        raise HTTPException(422, "result must be MET, UNMET, BLOCKED or ERROR")
    with db.transaction(request.app.state.db_path) as conn:
        row = load_job(conn, ref)
        run_id = conn.execute(
            "INSERT INTO runs (job_id, run_dir, type, started_at, finished_at, result) "
            "VALUES (?,?,?,?,?,?)", (row["id"], body.run_dir, body.type, body.started_at,
                                     body.finished_at or None, body.result or None)).lastrowid
        add_trail(conn, row["id"], actor, "note", f"task run {body.run_dir}: {body.result or 'started'}")
    return {"run_id": run_id, "job_id": row["id"]}
