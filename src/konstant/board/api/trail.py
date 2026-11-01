"""The append-only trail: read it, or append a note or a finding."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from konstant.board import db
from konstant.board.api.deps import Actor, add_trail, load_job, reader, trail_rows, writer

router = APIRouter()
APPEND_KINDS = ("note", "finding")   # every other kind is written by the board itself


class NoteIn(BaseModel):
    body: str
    kind: str = "note"


@router.get("/api/jobs/{ref}/trail")
def get_trail(ref: str, request: Request, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        return {"trail": trail_rows(conn, load_job(conn, ref)["id"])}


@router.post("/api/jobs/{ref}/trail")
def append(ref: str, body: NoteIn, request: Request, actor: Actor = Depends(writer)):
    if body.kind == "escalation" and actor.label == "factory":
        pass              # the factory identity records an escalation (docs/LEVEL5.md 6.3)
    elif body.kind not in APPEND_KINDS:
        raise HTTPException(422, f"kind {body.kind!r} is reserved; append kinds are "
                                 f"{', '.join(APPEND_KINDS)}")
    if not body.body.strip():
        raise HTTPException(422, "a note needs text")
    with db.transaction(request.app.state.db_path) as conn:
        job = load_job(conn, ref)
        tid = add_trail(conn, job["id"], actor, body.kind, body.body.strip())
    return {"job_id": job["id"], "trail_id": tid, "kind": body.kind}
