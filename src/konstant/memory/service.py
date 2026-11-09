"""Memory operations, as the board routes call them (board/api/memory.py). The caller's identity
is the board's Actor (label, role) from its token, never a request field.

Every write: redact secrets (board/redact.py) -> the store-time scan (guard.py) -> one file in the
writer's pool and folder -> one commit in memory/.git authored by the writer -> one append-only
`memory_writes` row -> the index updated for that file. A refused write is recorded as well (state
`refused`), and when the writer is a phase of a job (its run names one), as a `finding` on that
job's trail with the payload `{"memory_refused": <kind>}`, which only the board can write and the
verifier reads (verify/holdout.py). Every read labels each note with its source job and whether
that job reached `verified`, verified-job lessons first (`label`).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time

from konstant.board import db
from konstant.board.redact import redact
from konstant.memory import embed as embed_mod
from konstant.memory import guard, note as note_mod
from konstant.memory.index import Index
from konstant.memory.vault import Vault, VaultError, safe_rel

VAULT_DIR = "memory"
INDEX_FILE = "var/memory/index.db"
_LOCK = threading.Lock()
_TAG = re.compile(r"^[A-Za-z][\w/-]{0,63}$")
_RUN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
TAGS_MAX = 16


class MemoryRefused(Exception):
    def __init__(self, message: str, code: int = 422):
        super().__init__(message)
        self.message, self.code = message, code


def vault(cfg) -> Vault:
    return Vault(cfg.home / VAULT_DIR)


CHROMA_DIR = "var/memory/chroma"


def index(cfg) -> Index:
    vectors = None
    if settings(cfg)["engine"] == "chroma":           # the optional extra (memory/chroma.py)
        from konstant.memory.chroma import ChromaMissing, ChromaVectors
        try:
            vectors = ChromaVectors(cfg.home / CHROMA_DIR)
        except ChromaMissing as exc:
            raise MemoryRefused(str(exc), 503) from None
    return Index(cfg.home / INDEX_FILE, vault(cfg), vectors)


def settings(cfg) -> dict:
    return cfg.data["memory"]


def share(cfg) -> bool:
    """Whether notes konstant did not write are served ([confinement] memory_share)."""
    return bool(cfg.confinement().memory_share)


def embedder(cfg):
    return embed_mod.from_config(settings(cfg))


def provenance(conn) -> dict:
    """{path: (job id or None, sha256)} of konstant's latest stored write of each path."""
    out = {}
    for r in conn.execute("SELECT path, job_id, sha256 FROM memory_writes WHERE "
                          "state='stored' ORDER BY id"):
        out[r["path"]] = (r["job_id"], r["sha256"])
    return out


VERIFIED = ("verified",)


def label(db_path, hits: list) -> list:
    """Each hit gets its source job and whether that job reached `verified` (owner decision
    2026-11-08: a wrong lesson must not spread as truth), and verified-job lessons rank first
    (the relevance order is kept inside each tier). The job comes from the board's own record of
    the write, never from the note's frontmatter, and only while the note is konstant's write."""
    with db.reading(db_path) as conn:
        prov = provenance(conn)
        status = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM jobs")}
    for h in hits:
        job = prov.get(h["path"], (None, None))[0] if h.get("attributed", True) else None
        h["job"] = job
        h["verified"] = status.get(job) in VERIFIED if job is not None else None
        h["trust"] = (f"verified job {job}" if h["verified"] else
                      f"job {job} not verified ({status.get(job, 'unknown')})" if job is not None
                      else "no job" if h.get("attributed", True) else "not written by konstant")
    return sorted(hits, key=lambda h: 0 if h["verified"] else 1)


def attributed(conn) -> dict:
    """{path: sha256 of konstant's latest stored write}."""
    out = {}
    for r in conn.execute("SELECT path, sha256 FROM memory_writes WHERE state='stored' "
                          "ORDER BY id"):
        out[r["path"]] = r["sha256"]
    return out


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def job_of_run(cfg, run: str):
    """The job a phase's run works for: var/runs/<run>/record.json (machinery: a phase cannot
    write it). None when the run is unknown or has no job."""
    if not run or not _RUN.match(run):
        return None
    try:
        rec = json.loads((cfg.var / "runs" / run / "record.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    job = rec.get("job")
    return int(job) if isinstance(job, int) or (isinstance(job, str) and job.isdigit()) else None


def _tags(raw) -> list:
    out = []
    for t in raw or []:
        t = str(t).strip().lstrip("#")
        if not _TAG.match(t):
            raise MemoryRefused(f"tag {t!r}: letters, digits, _, -, / (starts with a letter)")
        out.append(t)
    if len(out) > TAGS_MAX:
        raise MemoryRefused(f"at most {TAGS_MAX} tags")
    return list(dict.fromkeys(out))


def _briefs(conn):
    def get(job_id):
        r = conn.execute("SELECT brief, acceptance FROM jobs WHERE id=?", (job_id,)).fetchone()
        return f"{r['brief'] or ''}\n{r['acceptance'] or ''}" if r else ""
    return get


def _record(conn, actor, **row) -> int:
    cols = {"actor": actor.label, "role": actor.role, **row}
    return conn.execute(f"INSERT INTO memory_writes ({', '.join(cols)}) VALUES "
                        f"({', '.join('?' * len(cols))})", tuple(cols.values())).lastrowid


def _free(v: Vault, rel: str) -> str:
    stem, n = rel[:-3], 2
    while (v.root / rel).exists():
        rel, n = f"{stem} {n}.md", n + 1
    return rel


def note_path(v: Vault, ns: str, writer: str, kind: str, title: str) -> str:
    """The vault path of a new write. In the shared pool the file name is the title (Obsidian
    resolves [[Title]]). In the SEALED pool it is opaque - a random id for a fact, a hash of the
    title for a named note (so a rewrite replaces it) - because the path is recorded where
    producers can read it (the board DB's memory_writes, the trail): a name built from the text
    would carry the judges' lesson out through the glass (REVIEW L5-R1 H-03)."""
    day = time.strftime('%Y-%m-%d', time.gmtime())
    if ns == guard.SEALED:
        if kind == "fact":
            return f"{ns}/{writer}/facts/{day} {secrets.token_hex(8)}.md"
        digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
        return f"{ns}/{writer}/note {digest}.md"
    name = note_mod.file_title(title)
    if kind == "fact":
        return _free(v, f"{ns}/{writer}/facts/{day} {name}.md")
    return f"{ns}/{writer}/{name}.md"


def write(cfg, db_path, actor, *, kind: str, text: str, title: str = "", tags=(), links=(),
          run: str = "") -> dict:
    """Store a fact (`kind` fact: a new file under <pool>/<writer>/facts/) or write a named note
    (`kind` note: <pool>/<writer>/<title>.md, created or replaced). The pool is the writer's
    (guard.write_pool: the judges' sealed pool, everyone else's shared one)."""
    from konstant.board.api.deps import add_trail
    from konstant.holdout import store as hstore
    mem = settings(cfg)
    if not mem["enabled"]:
        raise MemoryRefused("memory is off ([memory] enabled = false)", 409)
    try:
        ns = guard.write_pool(actor.label)
    except guard.StoreRefused as exc:
        raise MemoryRefused(exc.message, 403) from None
    text = redact(text or "").strip()
    if not text:
        raise MemoryRefused("a memory note needs text")
    if len(text.encode("utf-8")) > mem["max_note_bytes"]:
        raise MemoryRefused(f"a note is at most {mem['max_note_bytes']} bytes ([memory] "
                          "max_note_bytes)", 413)
    title = redact(title or "").strip() or (note_mod.title_from(text) if kind == "fact" else "")
    if not title:
        raise MemoryRefused("a note needs a title")
    tags = _tags(tags)
    links = [note_mod.file_title(str(x)) for x in links or [] if str(x).strip()][:32]
    run = run if run and _RUN.match(run) else ""
    job = job_of_run(cfg, run)
    with _LOCK:
        with db.transaction(db_path) as conn:
            if job is not None and not conn.execute("SELECT 1 FROM jobs WHERE id=?",
                                                    (job,)).fetchone():
                job = None
            try:
                guard.scan("\n".join([title, text, " ".join(tags)]), hstore.root(cfg),
                           _briefs(conn))
            except guard.StoreRefused as exc:
                _record(conn, actor, pool=ns, kind=kind, state="refused", reason=exc.kind,
                        run=run or None, job_id=job)
                if job is not None:
                    add_trail(conn, job, actor, "finding",
                              f"memory store refused ({exc.kind}): {exc.message}",
                              payload={"memory_refused": exc.kind, "run": run})
                refused = exc
            else:
                refused = None
        if refused is not None:
            raise MemoryRefused(refused.message, 422)
        v = vault(cfg)
        rel = note_path(v, ns, actor.label, kind, title)
        rel = safe_rel(rel)
        created = _now()
        if kind == "note" and (v.root / rel).is_file():
            try:
                created = note_mod.split(v.read(rel))[0].get("created") or created
            except (OSError, VaultError):
                pass
        meta = {"title": title, "tags": tags, "actor": actor.label, "kind": kind,
                "created": str(created), "updated": _now()}
        if run:
            meta["run"] = run
        if job is not None:
            meta["job"] = job
        body = text + ("\n\nRelated: " + ", ".join(f"[[{x}]]" for x in links) if links else "")
        content = note_mod.render(meta, body)
        try:
            commit = v.write(rel, content, actor.label, f"{kind} {rel} by {actor.label}"
                             + (f" (run {run})" if run else ""))
        except VaultError as exc:
            raise MemoryRefused(str(exc), 503) from None
        sha = note_mod.sha256(content)
        with db.transaction(db_path) as conn:
            _record(conn, actor, path=rel, pool=ns, kind=kind, state="stored",
                    sha256=sha, commit_sha=commit, run=run or None, job_id=job)
            attr = attributed(conn)
        stats = index(cfg).sync(attr, embedder(cfg), only=[rel])
    return {"path": rel, "pool": ns, "kind": kind, "title": title, "commit": commit,
            "sha256": sha, "job": job, "embed_error": stats.get("embed_error", "")}


def _sync(cfg, db_path) -> dict:
    with db.reading(db_path) as conn:
        attr = attributed(conn)
    with _LOCK:
        return index(cfg).sync(attr, embedder(cfg))


def scope(cfg, actor, pool: str = "") -> set:
    ns = guard.readable(actor.label)
    if pool:
        if pool not in guard.POOLS:
            raise MemoryRefused(f"unknown pool {pool!r}", 404)
        if pool not in ns:
            raise MemoryRefused(f"pool {pool!r} is not readable by {actor.label}", 403)
        ns = {pool}
    return ns


def recall(cfg, db_path, actor, query: str, limit: int = 0, pool: str = "") -> dict:
    if not settings(cfg)["enabled"]:
        raise MemoryRefused("memory is off ([memory] enabled = false)", 409)
    ns = scope(cfg, actor, pool)
    limit = max(1, min(int(limit or settings(cfg)["recall_limit"]), 50))
    stats = _sync(cfg, db_path)
    hits, mode = index(cfg).search(query, ns, not share(cfg), limit, embedder(cfg))
    hits = label(db_path, hits)
    if stats.get("embed_error") and mode == "hybrid":
        mode = f"hybrid (some notes have no vector yet: {stats['embed_error']})"
    return {"query": query, "mode": mode, "hits": hits, "pools": sorted(ns),
            "shared": share(cfg)}


def recent(cfg, db_path, actor, limit: int = 20, pool: str = "") -> dict:
    ns = scope(cfg, actor, pool)
    _sync(cfg, db_path)
    idx = index(cfg)
    hidden = sum(c for n, c in idx.counts().items() if n not in ns)
    return {"notes": label(db_path, idx.recent(ns, not share(cfg), max(1, min(int(limit), 200)))),
            "pools": sorted(ns), "hidden": hidden, "shared": share(cfg)}


def show(cfg, db_path, actor, rel: str) -> dict:
    try:
        rel = safe_rel(rel)
    except VaultError as exc:
        raise MemoryRefused(str(exc), 404) from None
    if not guard.can_read(actor.label, rel):
        raise MemoryRefused(f"{rel}: pool {guard.pool_of(rel)!r} is not readable by "
                          f"{actor.label}", 403)
    _sync(cfg, db_path)
    row = index(cfg).row(rel)
    if row is None or (not share(cfg) and not row["attributed"]):
        raise MemoryRefused(f"{rel}: no such note served (notes konstant did not write are served "
                          "only with [confinement] memory_share)", 404)
    text = vault(cfg).read(rel)
    n = note_mod.parse(text, rel)
    return {"path": rel, "pool": guard.pool_of(rel), "title": n.title,
            "meta": {k: str(v) if not isinstance(v, (list, int)) else v
                     for k, v in n.meta.items()},
            "tags": n.tags, "links": n.links, "body": n.body, "attributed": bool(row["attributed"])}


EXPORT_MAX = 2000


def export(cfg, db_path, actor) -> dict:
    """Every note `actor` may read, whole (the scenario writer's read-only view, memory/view.py):
    the newest EXPORT_MAX, each with its trust label."""
    ns = scope(cfg, actor)
    _sync(cfg, db_path)
    idx = index(cfg)
    notes = label(db_path, idx.recent(ns, not share(cfg), EXPORT_MAX))
    v = vault(cfg)
    out = []
    for n in notes:
        try:
            out.append({**n, "text": v.read(n["path"])})
        except (OSError, VaultError):
            continue
    return {"notes": out, "pools": sorted(ns)}


def history(cfg, db_path, actor, limit: int = 50) -> dict:
    ns = guard.readable(actor.label)
    with db.reading(db_path) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM memory_writes ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),))]
    return {"writes": [r for r in rows if r["pool"] in ns]}


def reindex(cfg, db_path) -> dict:
    with db.reading(db_path) as conn:
        attr = attributed(conn)
    with _LOCK:
        vault(cfg).ensure()
        stats = index(cfg).rebuild(attr, embedder(cfg))
    return {**stats, "notes": len(vault(cfg).files())}
