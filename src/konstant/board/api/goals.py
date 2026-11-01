"""Goals on the board (docs/LEVEL5.md 4.0, 4.1): file, confirm, read, pause/resume/cancel, and
the goal's intake state.

POST /api/goals {spec, source, session}: the board validates the TOML with factory/goal.py.
`source = "file"` needs the owner role and makes the goal active at once; `source = "chat"` (the
owner's orchestrator session is the intake, 4.0) needs a role of `[factory] goal_roles` and a
session id, and records the goal as `proposed`: it becomes active only by `confirm` from that same
session, which the konstant-gate plugin sends when the owner's NEXT message in it is a yes (4.0
step 2), and anything else withdraws it. Only role tokens file goals (a factory identity or a
phase never does). An active goal's spec bytes are copied to var/factory/goals/<id>.toml (0400,
machinery: no phase writes it) and their sha256 is the goal's immutable spec_sha256 (DB trigger).

POST /api/goals/{ref}/intake {state} is the factory identity's alone: the goal's jobs are filed
(by the planner identity) and DoD-reviewed only while it holds `filing` (jobs.py, lifecycle.py),
so no phase of the intake run can file or review around the deterministic filing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from konstant.board import db, tree
from konstant.board.api.deps import Actor, reader, writer
from konstant.board.redact import redact

router = APIRouter()
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
FACTORY = "factory"
INTAKE_FROM = {"planning": ("none", "refused", "planning"), "filing": ("planning",),
               "filed": ("filing",), "refused": ("planning", "filing")}
MAX_SPEC = 64 * 1024


class GoalIn(BaseModel):
    spec: str = Field(max_length=MAX_SPEC)
    source: str = "file"
    session: str = ""


class SessionIn(BaseModel):
    session: str = ""
    reason: str = ""


class IntakeIn(BaseModel):
    state: str


def copy_path(cfg, slug: str) -> Path:
    return cfg.home / "var" / "factory" / "goals" / f"{slug}.toml"


def write_copy(cfg, slug: str, data: bytes) -> None:
    """The factory's copy of a goal: written once, 0400 in 0700 directories."""
    path = copy_path(cfg, slug)
    for d in (path.parent.parent, path.parent):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(d, 0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    except FileExistsError:
        if path.read_bytes() != data:
            raise HTTPException(409, f"{path} exists with other content: a goal copy is written "
                                     "once") from None
        return
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def is_role_token(actor: Actor) -> bool:
    return actor.label == actor.role


def load_goal(conn, ref: str):
    ref = str(ref).strip()
    if ref.isdigit():
        row = conn.execute("SELECT * FROM goals WHERE id=?", (int(ref),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM goals WHERE slug=? ORDER BY status = 'withdrawn', id "
                           "DESC LIMIT 1", (ref,)).fetchone()
    if row is None:
        raise HTTPException(404, f"goal {ref} not found")
    return row


def goal_spec(row) -> dict:
    return json.loads(row["spec_json"])


def jobs_of(conn, goal_id: int) -> list:
    rows = conn.execute("SELECT id, title, type, status, ship_mode FROM jobs WHERE goal_id=? "
                        "ORDER BY id", (goal_id,)).fetchall()
    return [{**dict(r), "display_id": tree.display_id(conn, r["id"])} for r in rows]


def serialize(conn, row, jobs: bool = False) -> dict:
    out = {k: row[k] for k in row.keys() if k not in ("spec_json", "spec_text")}
    out["spec"] = goal_spec(row)
    proj = conn.execute("SELECT slug FROM projects WHERE id=?", (row["project_id"],)).fetchone()
    out["project"] = proj["slug"] if proj else None
    out["limits"] = out["spec"]["limits"]
    if jobs:
        out["jobs"] = jobs_of(conn, row["id"])
        counts: dict = {}
        for j in out["jobs"]:
            counts[j["status"]] = counts.get(j["status"], 0) + 1
        out["jobs_by_state"] = counts
    return out


def _touch(conn, gid: int, **cols) -> None:
    assigns = ", ".join(f"{k}=?" for k in cols)
    conn.execute(f"UPDATE goals SET {assigns}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                 "WHERE id=?", (*cols.values(), gid))


@router.post("/api/goals")
def add_goal(body: GoalIn, request: Request, actor: Actor = Depends(writer)):
    from konstant.factory import goal as goal_mod
    cfg = request.app.state.cfg
    source = body.source.strip()
    if source not in ("file", "chat"):
        raise HTTPException(422, "source is file or chat")
    if not is_role_token(actor):
        raise HTTPException(403, f"a goal is filed by the owner (or, from the owner's chat, a "
                                 f"role of [factory] goal_roles), never by the {actor.label} "
                                 "identity")
    session = body.session.strip()
    if source == "file" and actor.role != "owner":
        raise HTTPException(403, f"goal add from a file requires role owner (this token is "
                                 f"{actor.role}); the orchestrator files a goal only from the "
                                 "owner's chat (--from-chat), where the owner confirms it")
    if source == "chat":
        roles = cfg.data["factory"]["goal_roles"]
        if actor.role not in roles:
            raise HTTPException(403, f"goal add --from-chat requires role {', '.join(roles)} "
                                     f"([factory] goal_roles; this token is {actor.role})")
        if not SESSION.fullmatch(session):
            raise HTTPException(422, "a chat goal names the session it was asked in (--session)")
    try:
        spec = goal_mod.parse(body.spec, cfg.data["factory"]["defaults"],
                              cfg.data["holdout"]["min_per_job"])
    except goal_mod.GoalError as exc:
        raise HTTPException(422, "\n".join(exc.reasons)) from None
    data = body.spec.encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    slug = spec["goal"]["id"]
    status = "active" if source == "file" else "proposed"
    with db.transaction(request.app.state.db_path) as conn:
        proj = conn.execute("SELECT id FROM projects WHERE slug=?",
                            (spec["goal"]["project"],)).fetchone()
        if proj is None:
            raise HTTPException(422, f"goal: project {spec['goal']['project']!r} is not a "
                                     "konstant project (`konstant project add` it first)")
        taken = conn.execute("SELECT status FROM goals WHERE slug=? AND status <> 'withdrawn'",
                             (slug,)).fetchone()
        if taken:
            raise HTTPException(409, f"goal {slug} exists ({taken['status']}): a goal id is used "
                                     "once")
        if status == "active":
            write_copy(cfg, slug, data)
        gid = conn.execute(
            "INSERT INTO goals (slug, project_id, spec_text, spec_json, spec_sha256, source, "
            "session, status, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (slug, proj["id"], body.spec, json.dumps(spec, sort_keys=True), sha, source,
             session or None, status, actor.label)).lastrowid
        out = serialize(conn, conn.execute("SELECT * FROM goals WHERE id=?", (gid,)).fetchone())
    out["summary"] = goal_mod.summary(spec)
    return out


@router.get("/api/goals")
def list_goals(request: Request, status: str = "", session: str = "",
               actor: Actor = Depends(reader)):
    q, args = "SELECT * FROM goals WHERE 1=1", []
    if status:
        states = [s for s in status.split(",") if s]
        q += " AND status IN (%s)" % ",".join("?" * len(states))
        args += states
    if session:
        q += " AND session=?"
        args.append(session)
    with db.reading(request.app.state.db_path) as conn:
        return {"goals": [serialize(conn, r) for r in conn.execute(q + " ORDER BY id",
                                                                    args).fetchall()]}


@router.get("/api/goals/{ref}")
def show_goal(ref: str, request: Request, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        return serialize(conn, load_goal(conn, ref), jobs=True)


def _session_verb(request, ref: str, body: SessionIn, actor: Actor, verb: str) -> dict:
    """confirm / withdraw a chat proposal: the same session, a role token of goal_roles."""
    cfg = request.app.state.cfg
    if not is_role_token(actor) or actor.role not in cfg.data["factory"]["goal_roles"]:
        raise HTTPException(403, f"{verb} of a chat goal requires role "
                                 f"{', '.join(cfg.data['factory']['goal_roles'])}")
    with db.transaction(request.app.state.db_path) as conn:
        row = load_goal(conn, ref)
        if row["status"] != "proposed":
            raise HTTPException(409, f"goal {row['slug']} is {row['status']}, not proposed")
        if (body.session or "").strip() != (row["session"] or ""):
            raise HTTPException(403, f"goal {row['slug']} was proposed in another session: only "
                                     "the owner's answer in that session confirms or withdraws it")
        if verb == "confirm":
            from konstant.factory import goal as goal_mod
            spec = goal_spec(row)
            text = _spec_text(row)
            write_copy(cfg, row["slug"], text)
            _touch(conn, row["id"], status="active")
        else:
            _touch(conn, row["id"], status="withdrawn")
        out = serialize(conn, conn.execute("SELECT * FROM goals WHERE id=?",
                                           (row["id"],)).fetchone())
    if verb == "confirm":
        out["summary"] = goal_mod.summary(spec)
    out["reason"] = redact((body.reason or "").strip())[:300]
    return out


def _spec_text(row) -> bytes:
    """The proposal's own bytes; their sha256 must still equal the recorded spec_sha256."""
    data = row["spec_text"].encode("utf-8")
    if hashlib.sha256(data).hexdigest() != row["spec_sha256"]:
        raise HTTPException(409, f"goal {row['slug']}: the spec does not match its sha256")
    return data


@router.post("/api/goals/{ref}/confirm")
def confirm(ref: str, body: SessionIn, request: Request, actor: Actor = Depends(writer)):
    return _session_verb(request, ref, body, actor, "confirm")


@router.post("/api/goals/{ref}/withdraw")
def withdraw(ref: str, body: SessionIn, request: Request, actor: Actor = Depends(writer)):
    return _session_verb(request, ref, body, actor, "withdraw")


STATUS_VERBS = {"pause": (("active",), "paused"), "resume": (("paused",), "active"),
                "cancel": (("proposed", "active", "paused"), "stopped")}


def status_verb(ref: str, verb: str, request: Request, actor: Actor) -> dict:
    allowed = actor.role == "owner" or (verb == "pause" and actor.label == FACTORY)
    if not allowed:
        raise HTTPException(403, f"goal {verb} requires role owner"
                                 + (" (or the factory identity)" if verb == "pause" else ""))
    sources, target = STATUS_VERBS[verb]
    with db.transaction(request.app.state.db_path) as conn:
        row = load_goal(conn, ref)
        if row["status"] not in sources:
            raise HTTPException(409, f"goal {row['slug']} is {row['status']}; {verb} is legal "
                                     f"from {', '.join(sources)}")
        _touch(conn, row["id"], status=target)
        return serialize(conn, conn.execute("SELECT * FROM goals WHERE id=?",
                                            (row["id"],)).fetchone())


@router.post("/api/goals/{ref}/pause")
def pause(ref: str, request: Request, actor: Actor = Depends(writer)):
    return status_verb(ref, "pause", request, actor)


@router.post("/api/goals/{ref}/resume")
def resume(ref: str, request: Request, actor: Actor = Depends(writer)):
    return status_verb(ref, "resume", request, actor)


@router.post("/api/goals/{ref}/cancel")
def cancel(ref: str, request: Request, actor: Actor = Depends(writer)):
    return status_verb(ref, "cancel", request, actor)


@router.post("/api/goals/{ref}/intake")
def intake_state(ref: str, body: IntakeIn, request: Request, actor: Actor = Depends(writer)):
    """The goal's intake state, moved by the factory identity only (module docstring)."""
    from konstant.board.policy import role_of
    if actor.label != FACTORY or role_of(actor.label) != actor.role:
        raise HTTPException(403, "a goal's intake state is moved by the factory identity only")
    state = body.state.strip()
    if state not in INTAKE_FROM:
        raise HTTPException(422, f"intake state is one of {', '.join(INTAKE_FROM)}")
    with db.transaction(request.app.state.db_path) as conn:
        row = load_goal(conn, ref)
        if state == "planning" and row["status"] != "active":
            raise HTTPException(409, f"goal {row['slug']} is {row['status']}: intake runs for "
                                     "an active goal")
        if row["intake"] not in INTAKE_FROM[state]:
            raise HTTPException(409, f"goal {row['slug']} intake is {row['intake']}; {state} "
                                     f"follows {', '.join(INTAKE_FROM[state])}"
                                     + (" (a goal is taken in once)" if row["intake"] == "filed"
                                        else ""))
        _touch(conn, row["id"], intake=state)
        return serialize(conn, conn.execute("SELECT * FROM goals WHERE id=?",
                                            (row["id"],)).fetchone(), jobs=True)
