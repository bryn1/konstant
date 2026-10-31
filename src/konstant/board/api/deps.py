"""Shared route plumbing: auth dependencies, job loading and serialisation, trail writes."""
from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

from konstant.board import auth, db, tree
from konstant.board.redact import redact, redact_obj
from konstant.board.transitions import Refused


@dataclass(frozen=True)
class Actor:
    label: str
    role: str


def _token(authorization: str) -> str:
    """RFC 7235: the auth scheme is case-insensitive (REVIEW F-31)."""
    scheme, _, value = authorization.strip().partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def reader(request: Request, authorization: str = Header(default="")) -> Actor:
    """Any valid token reads."""
    with db.reading(request.app.state.db_path) as conn:
        found = auth.lookup(conn, _token(authorization))
    if not found:
        raise HTTPException(401, "invalid or missing token (Authorization: Bearer <token>)")
    return Actor(*found)


def writer(request: Request, authorization: str = Header(default="")) -> Actor:
    """Every mutating route depends on this: `viewer` is read-only."""
    actor = reader(request, authorization)
    if actor.role == "viewer":
        raise HTTPException(403, "the viewer token is read-only; write routes refuse it")
    return actor


def refuse(exc: Exception):
    if isinstance(exc, Refused):
        raise HTTPException(exc.code, exc.message)
    if isinstance(exc, tree.TreeRefused):
        raise HTTPException(exc.code, str(exc))
    raise exc


def load_job(conn, ref):
    job_id = tree.resolve_path(conn, ref)
    if job_id is None:
        raise HTTPException(404, f"job {ref} not found")
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def serialize(conn, row) -> dict:
    out = dict(row)
    out["evidence"] = json.loads(out.pop("evidence_json")) if row["evidence_json"] else None
    out["approval_required"] = bool(out["approval_required"])
    out["display_id"] = tree.display_id(conn, row["id"])
    out["depth"] = tree.depth(conn, row["id"])
    proj = conn.execute("SELECT slug FROM projects WHERE id=?", (row["project_id"],)).fetchone()
    out["project"] = proj["slug"] if proj else None
    return out


def add_trail(conn, job_id: int, actor: Actor, kind: str, body: str = "", payload=None) -> int:
    cur = conn.execute(
        "INSERT INTO trail (job_id, actor, role, kind, body, payload_json) VALUES (?,?,?,?,?,?)",
        (job_id, actor.label, actor.role, kind, redact(body or ""),
         json.dumps(redact_obj(payload)) if payload is not None else None))
    return cur.lastrowid


def trail_rows(conn, job_id: int) -> list:
    rows = conn.execute("SELECT * FROM trail WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json")) if r["payload_json"] else None
        out.append(d)
    return out


def set_status(conn, job_id: int, status: str, **fields) -> None:
    cols = {"status": status, **fields}
    assigns = ", ".join(f"{k}=?" for k in cols)
    conn.execute(f"UPDATE jobs SET {assigns}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                 "WHERE id=?", (*cols.values(), job_id))
