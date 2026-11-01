"""FastAPI app factory: policy + catalog + DB checked at start, routes, read-only static view.

The board refuses to start when [board.policy] is malformed, the catalog is invalid, or the DB
schema is not the newest (run `konstant board init`): a board that started anyway would be
running with a disarmed gate or against a schema it does not understand.
A request body over MAX_BODY is refused with 413 before it is read (REVIEW F-22); the role tokens
in var/secrets/ are registered with the redactor, so a raw token never lands in the DB.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from konstant import __version__, catalog as catalog_mod
from konstant.board import migrate, policy as policy_mod, redact
from konstant.board.api import goals, holdouts, jobs, lifecycle, projects, tokens, trail, verify
from konstant.config import Config

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 1024 * 1024


def register_tokens(secrets_dir: Path) -> None:
    for f in sorted(Path(secrets_dir).glob("*.token")) if Path(secrets_dir).is_dir() else []:
        try:
            redact.register_secrets([f.read_text(encoding="utf-8").strip()])
        except OSError:
            pass


class StartupError(Exception):
    pass


def create_app(cfg: Config) -> FastAPI:
    pol = policy_mod.from_mapping(cfg.data["board"]["policy"])
    cat = catalog_mod.load(catalog_mod.find_root(cfg.home, cfg.data["catalog"]["path"]))
    db_path = cfg.db_path
    have, want = migrate.current_version(db_path), migrate.target_version()
    if have != want:
        raise StartupError(f"board DB {db_path} is at schema {have}, this konstant needs {want}: "
                           "run `konstant board init`")

    app = FastAPI(title="konstant board", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.cfg, app.state.policy, app.state.catalog = cfg, pol, cat
    app.state.db_path = db_path
    register_tokens(cfg.secrets_dir)

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        size = request.headers.get("content-length", "")
        if size.isdigit() and int(size) > MAX_BODY:
            return JSONResponse({"detail": f"request body over {MAX_BODY} bytes"}, status_code=413)
        if request.method in ("POST", "PUT", "PATCH") and not size.isdigit() and \
                "chunked" in request.headers.get("transfer-encoding", "").lower():
            return JSONResponse({"detail": "send a Content-Length (no chunked bodies)"},
                                status_code=411)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "schema": want}

    @app.get("/api/catalog")
    def catalog_types():
        return {"types": {k: {"agent": v["agent"], "deliverable": v["deliverable"]}
                          for k, v in cat.types.items()},
                "review_types": cat.review_types}

    for mod in (projects, jobs, lifecycle, verify, trail, tokens, holdouts, goals):
        app.include_router(mod.router)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app
