"""Memory routes (wave L5-M; konstant/memory/). The caller's identity is its token's label: it
decides the pool a write lands in and the pools a read may see (memory/guard.py).

  GET  /api/memory/recall?q=&limit=&pool=   recall (lexical, or hybrid with embeddings)
  GET  /api/memory/notes?limit=&pool=       recent notes (the web view's Memory tab)
  GET  /api/memory/note?path=                    one note
  GET  /api/memory/writes?limit=                 the attributed write log (memory_writes)
  GET  /api/memory/export                        every note the caller reads, whole (the
                                                 scenario writer's read-only view)
  POST /api/memory/store   {text, title?, tags?, links?, run?}         a fact
  POST /api/memory/note    {title, text, tags?, links?, run?}          a named note
  POST /api/memory/reindex                       rebuild the index from the vault (owner,
                                                 orchestrator)
Any valid token reads (viewer included: it never sees the sealed pool); the viewer
token never writes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from konstant.board.api.deps import Actor, reader, writer
from konstant.memory import service

router = APIRouter()


class StoreIn(BaseModel):
    text: str
    title: str = ""
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    run: str = ""


def _call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except service.MemoryRefused as exc:
        raise HTTPException(exc.code, exc.message) from None


def _ctx(request: Request) -> tuple:
    return request.app.state.cfg, request.app.state.db_path


@router.get("/api/memory/recall")
def recall(request: Request, q: str = "", limit: int = 0, pool: str = "",
           actor: Actor = Depends(reader)):
    return _call(service.recall, *_ctx(request), actor, q, limit, pool)


@router.get("/api/memory/notes")
def notes(request: Request, limit: int = 20, pool: str = "",
          actor: Actor = Depends(reader)):
    return _call(service.recent, *_ctx(request), actor, limit, pool)


@router.get("/api/memory/note")
def note(request: Request, path: str, actor: Actor = Depends(reader)):
    return _call(service.show, *_ctx(request), actor, path)


@router.get("/api/memory/export")
def export(request: Request, actor: Actor = Depends(reader)):
    """Every note the caller may read, whole: the scenario writer's read-only view."""
    return _call(service.export, *_ctx(request), actor)


@router.get("/api/memory/writes")
def writes(request: Request, limit: int = 50, actor: Actor = Depends(reader)):
    return _call(service.history, *_ctx(request), actor, limit)


@router.post("/api/memory/store")
def store(body: StoreIn, request: Request, actor: Actor = Depends(writer)):
    return _call(service.write, *_ctx(request), actor, kind="fact", text=body.text,
                 title=body.title, tags=body.tags, links=body.links, run=body.run)


@router.post("/api/memory/note")
def write_note(body: StoreIn, request: Request, actor: Actor = Depends(writer)):
    return _call(service.write, *_ctx(request), actor, kind="note", text=body.text,
                 title=body.title, tags=body.tags, links=body.links, run=body.run)


@router.post("/api/memory/reindex")
def reindex(request: Request, actor: Actor = Depends(writer)):
    if actor.role not in ("owner", "orchestrator"):
        raise HTTPException(403, "reindex: owner or orchestrator")
    return _call(service.reindex, *_ctx(request))
