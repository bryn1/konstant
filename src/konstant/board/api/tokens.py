"""Token administration (owner only): list roles/labels - never values - and rotate a role."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from konstant.board import auth, db, redact
from konstant.board.api.deps import Actor, reader, writer
from konstant.board.policy import ROLES

router = APIRouter()


class RotateIn(BaseModel):
    role: str


def _owner(actor: Actor) -> None:
    if actor.role != "owner":
        raise HTTPException(403, f"token administration requires role owner (this token is "
                                 f"{actor.role})")


@router.get("/api/whoami")
def whoami(actor: Actor = Depends(reader)):
    return {"label": actor.label, "role": actor.role}


@router.get("/api/tokens")
def list_tokens(request: Request, actor: Actor = Depends(reader)):
    _owner(actor)
    with db.reading(request.app.state.db_path) as conn:
        rows = conn.execute("SELECT id, role, label, active, created_at FROM tokens "
                            "ORDER BY id").fetchall()
    return {"tokens": [dict(r) for r in rows]}


@router.post("/api/tokens/rotate")
def rotate(body: RotateIn, request: Request, actor: Actor = Depends(writer)):
    _owner(actor)
    if body.role not in ROLES:
        raise HTTPException(422, f"unknown role {body.role!r}; roles are {', '.join(ROLES)}")
    with db.transaction(request.app.state.db_path) as conn:
        value = auth.rotate(conn, body.role)
    redact.register_secrets([value])
    return {"role": body.role, "token": value}
