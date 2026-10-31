"""Projects: each one owns a root job (depth 0) that every job without --parent is filed under.

A project path is a probe root and the verifier's re-run cwd, so it may not widen either: it is
refused when it resolves to /, the user's home, the workspace or any ancestor of it, or anything
under the workspace's var/ (REVIEW F-13). A relative path is relative to the workspace.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from konstant.board import db
from konstant.board.api.deps import Actor, add_trail, reader, writer
from konstant.board.redact import redact

router = APIRouter()
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PROJECT_ROLES = ("owner", "orchestrator")


def path_problem(home: Path, raw: str):
    """Why `raw` may not be a project path, or None."""
    home = Path(os.path.realpath(home))
    p = Path(raw)
    real = Path(os.path.realpath(p if p.is_absolute() else home / p))
    if real == Path("/") or real == Path(os.path.realpath(os.path.expanduser("~"))):
        return f"{raw} resolves to {real}: a project is a folder of its own, never / or home"
    if real == home or real in home.parents:
        return f"{raw} resolves to {real}, the workspace or a folder that contains it"
    var = home / "var"
    if real == var or var in real.parents:
        return f"{raw} resolves into the workspace's var/ (board, tokens, runs)"
    return None


class ProjectIn(BaseModel):
    slug: str
    name: str = ""
    path: str = ""


def _project(conn, row) -> dict:
    return dict(row)


@router.get("/api/projects")
def list_projects(request: Request, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
        return {"projects": [_project(conn, r) for r in rows]}


@router.post("/api/projects")
def add_project(body: ProjectIn, request: Request, actor: Actor = Depends(writer)):
    if actor.role not in PROJECT_ROLES:
        raise HTTPException(403, f"project add requires role {', '.join(PROJECT_ROLES)} "
                                 f"(this token is {actor.role})")
    if not SLUG.match(body.slug):
        raise HTTPException(422, f"bad slug {body.slug!r}: lowercase letters, digits and '-', "
                                 "starting with a letter or digit")
    name = redact(body.name.strip() or body.slug)
    path = body.path.strip() or f"projects/{body.slug}"
    why = path_problem(request.app.state.cfg.home, path)
    if why:
        raise HTTPException(422, f"refused project path: {why}")
    with db.transaction(request.app.state.db_path) as conn:
        if conn.execute("SELECT 1 FROM projects WHERE slug=?", (body.slug,)).fetchone():
            raise HTTPException(409, f"project {body.slug!r} already exists")
        pid = conn.execute("INSERT INTO projects (slug, name, path) VALUES (?,?,?)",
                           (body.slug, name, path)).lastrowid
        root = conn.execute(
            "INSERT INTO jobs (project_id, parent_id, type, title, status, requested_by) "
            "VALUES (?, NULL, 'project', ?, 'queued', ?)",
            (pid, f"[project:{body.slug}] {name}", actor.label)).lastrowid
        conn.execute("UPDATE projects SET root_job_id=? WHERE id=?", (root, pid))
        add_trail(conn, root, actor, "status", f"project {body.slug} created")
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return _project(conn, row)
