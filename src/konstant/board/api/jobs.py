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
    known = st.catalog.type_names()
    if jtype not in known:
        what = f"unknown type {jtype!r}" if jtype else "a type is required (--type)"
        raise HTTPException(422, f"{what}; known types: {', '.join(known)}")
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
        status = "waiting_approval" if body.approval else "queued"
        job_id = conn.execute(
            "INSERT INTO jobs (project_id, parent_id, type, title, brief, acceptance, status, "
            "priority, requested_by, after_id, approval_required, holdout_required) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (proj["id"], parent_id, jtype, title, brief, acceptance, status, body.priority,
             actor.label, after_id, int(body.approval), int(body.holdout_required))).lastrowid
        add_trail(conn, job_id, actor, "status", f"filed as {status}")
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
