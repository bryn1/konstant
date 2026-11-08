"""The recall index: a CACHE of the vault (`var/memory/index.db`), never a source of truth.

SQLite FTS5 from Python's standard library (bm25 ranking, unicode61 tokenizer, diacritics folded)
for lexical recall; with an embedder (embed.py) each note also gets a vector and recall fuses the
two rankings (reciprocal rank fusion). `sync` brings the index up to the vault by stat (path,
mtime, size) and content hash, so notes the owner edits with his own tools are seen at the next
recall; `rebuild` deletes the file and indexes the whole vault again. Each row records whether
the note is ATTRIBUTED: its content hash equals konstant's latest write of that path (the board's
`memory_writes`); a hand-edited or hand-made note is not (guard.py decides whether those are
served).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from konstant.memory import embed as embed_mod
from konstant.memory import guard
from konstant.memory import note as note_mod
from konstant.memory.vault import Vault, VaultError

SCHEMA = 1
RRF_K = 60
_FTS_OPT, _FTS_TOKENIZER = "tokenize", "unicode61 remove_diacritics 2"
_WORD = re.compile(r"\w{2,}", re.U)
_DDL = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS notes (
  path TEXT PRIMARY KEY, pool TEXT NOT NULL, title TEXT NOT NULL, tags TEXT NOT NULL,
  links TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL, updated TEXT NOT NULL,
  sha256 TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
  attributed INTEGER NOT NULL, body TEXT NOT NULL, vec BLOB, vec_model TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
  path UNINDEXED, title, tags, body, {_FTS_OPT} = '{_FTS_TOKENIZER}');
"""


class Index:
    def __init__(self, path, vault: Vault, vectors=None):
        self.path = Path(path)
        self.vault = vault
        self.vectors = vectors        # None: vectors in the `vec` column; else chroma.py

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        new = not self.path.exists()
        if new:
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.executescript(_DDL)
        conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA),))
        return conn

    def rebuild(self, attributed: dict, embedder=None) -> dict:
        """Drop the cache and index the whole vault again."""
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        if self.vectors is not None:
            self.vectors.delete(self.vectors.col.get(include=[])["ids"])
        return self.sync(attributed, embedder)

    def sync(self, attributed: dict, embedder=None, only: list | None = None) -> dict:
        """Bring the index up to the vault. `attributed`: {path: sha256 of konstant's latest
        write}. `only`: restrict to these paths (a write just made). Returns counts and the
        embedding state."""
        conn = self.connect()
        stats = {"indexed": 0, "removed": 0, "embedded": 0, "embed_error": ""}
        try:
            rows = {r["path"]: r for r in conn.execute(
                "SELECT path, mtime_ns, size, sha256, attributed FROM notes")}
            files = self.vault.files() if only is None else [p for p in only]
            seen = set()
            for rel in files:
                seen.add(rel)
                try:
                    st = (self.vault.root / rel).stat()
                except OSError:
                    continue
                old = rows.get(rel)
                if old is not None and old["mtime_ns"] == st.st_mtime_ns and \
                        old["size"] == st.st_size and \
                        bool(old["attributed"]) == (attributed.get(rel) == old["sha256"]):
                    continue
                try:
                    text = self.vault.read(rel)
                except (OSError, VaultError):
                    continue
                n = note_mod.parse(text, rel)
                self._upsert(conn, n, st, attributed.get(rel) == n.sha256)
                stats["indexed"] += 1
            if only is None:
                gone = sorted(set(rows) - seen)
                for rel in gone:
                    conn.execute("DELETE FROM notes WHERE path=?", (rel,))
                    conn.execute("DELETE FROM fts WHERE path=?", (rel,))
                    stats["removed"] += 1
                if gone and self.vectors is not None:
                    self.vectors.delete(gone)
            if embedder is not None:
                self._embed(conn, embedder, stats)
        finally:
            conn.close()
        return stats

    def _upsert(self, conn, n, st, attributed: bool) -> None:
        conn.execute("DELETE FROM fts WHERE path=?", (n.path,))
        conn.execute(
            "INSERT INTO notes (path, pool, title, tags, links, actor, kind, updated, sha256,"
            " mtime_ns, size, attributed, body, vec, vec_model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,"
            "NULL,NULL) ON CONFLICT(path) DO UPDATE SET pool=excluded.pool, "
            "title=excluded.title, tags=excluded.tags, links=excluded.links, actor=excluded.actor,"
            " kind=excluded.kind, updated=excluded.updated, sha256=excluded.sha256, "
            "mtime_ns=excluded.mtime_ns, size=excluded.size, attributed=excluded.attributed, "
            "body=excluded.body, vec=CASE WHEN notes.sha256 = excluded.sha256 THEN notes.vec "
            "END, vec_model=CASE WHEN notes.sha256 = excluded.sha256 THEN notes.vec_model END",
            (n.path, guard.pool_of(n.path), n.title, json.dumps(n.tags), json.dumps(n.links),
             n.actor,
             n.kind, n.updated, n.sha256, st.st_mtime_ns, st.st_size, int(attributed), n.body))
        conn.execute("INSERT INTO fts (path, title, tags, body) VALUES (?,?,?,?)",
                     (n.path, n.title, " ".join(n.tags), n.body))

    def _embed(self, conn, embedder, stats: dict) -> None:
        todo = conn.execute("SELECT path, pool, title, body FROM notes WHERE vec_model IS "
                            "NULL OR vec_model IS NOT ?", (embedder.name,)).fetchall()
        if not todo:
            return
        try:
            vecs = embedder.embed([f"{r['title']}\n{r['body']}"[:8000] for r in todo])
        except embed_mod.EmbedError as exc:
            stats["embed_error"] = str(exc)
            return
        if self.vectors is not None:          # Chroma keeps the vectors; the column marks them
            self.vectors.upsert([(r["path"], embed_mod.unpack(embed_mod.pack(v)), r["pool"])
                                 for r, v in zip(todo, vecs)])
        for r, v in zip(todo, vecs):
            conn.execute("UPDATE notes SET vec=?, vec_model=? WHERE path=?",
                         (None if self.vectors is not None else embed_mod.pack(v),
                          embedder.name, r["path"]))
            stats["embedded"] += 1

    # --- queries ------------------------------------------------------------------------
    @staticmethod
    def _scope(pools, attributed_only: bool) -> tuple:
        sql, args = [], []
        if pools is not None:
            ns = sorted(pools) or [""]
            sql.append(f"n.pool IN ({','.join('?' * len(ns))})")
            args += ns
        if attributed_only:
            sql.append("n.attributed = 1")
        return (" AND " + " AND ".join(sql)) if sql else "", args

    def search(self, query: str, pools=None, attributed_only: bool = True, limit: int = 8,
               embedder=None) -> tuple:
        """(hits, mode). hits: [{path, pool, title, actor, kind, updated, tags, snippet,
        score}]; mode: "lexical", "hybrid", or "lexical (...why the vectors were not used)"."""
        words = list(dict.fromkeys(w.lower() for w in _WORD.findall(query or "")))[:16]
        where, args = self._scope(pools, attributed_only)
        conn = self.connect()
        try:
            lex = []
            if words:
                fq = " OR ".join('"' + w.replace('"', '""') + '"' for w in words)
                lex = conn.execute(
                    "SELECT n.path, n.pool, n.title, n.actor, n.kind, n.updated, n.tags, "
                    "n.attributed, "
                    "snippet(fts, 3, '[', ']', '...', 14) AS snippet, bm25(fts) AS rank "
                    f"FROM fts JOIN notes n ON n.path = fts.path WHERE fts MATCH ?{where} "
                    "ORDER BY rank LIMIT ?", (fq, *args, limit * 4)).fetchall()
            mode, vec = "lexical", []
            if embedder is not None and (query or "").strip():
                try:
                    q = embed_mod.unpack(embed_mod.pack(embedder.embed([query])[0]))
                    vec = self._nearest(conn, q, embedder.name, where, args, pools,
                                        limit * 4)
                    mode = "hybrid"
                except embed_mod.EmbedError as exc:
                    mode = f"lexical ({exc})"
        finally:
            conn.close()
        return fuse(lex, vec, limit), mode

    def _nearest(self, conn, q, model: str, where: str, args: list, pools, k: int) -> list:
        """The k nearest notes IN SCOPE (pools, attribution: the SQLite catalog decides,
        whichever store holds the vectors)."""
        cols = ("n.path, n.pool, n.title, n.actor, n.kind, n.updated, n.tags, n.attributed, "
                "substr(n.body, 1, 160) AS snippet")
        if self.vectors is not None:
            best = dict(self.vectors.query(list(q), k * 2, pools))
            if not best:
                return []
            marks = ",".join("?" * len(best))
            rows = conn.execute(f"SELECT {cols} FROM notes n WHERE n.path IN ({marks}) AND "
                                f"n.vec_model = ?{where}", (*best, model, *args)).fetchall()
            scored = [(best[r["path"]], r) for r in rows]
        else:
            rows = conn.execute(f"SELECT {cols}, n.vec FROM notes n WHERE n.vec IS NOT NULL AND "
                                f"n.vec_model = ?{where}", (model, *args)).fetchall()
            scored = [(embed_mod.cosine(q, embed_mod.unpack(r["vec"])), r) for r in rows]
        scored.sort(key=lambda t: -t[0])
        return [r for s, r in scored[:k] if s > 0]

    def recent(self, pools=None, attributed_only: bool = True, limit: int = 20) -> list:
        where, args = self._scope(pools, attributed_only)
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT n.path, n.pool, n.title, n.actor, n.kind, n.updated, n.tags, "
                "substr(n.body, 1, 160) AS snippet, n.attributed FROM notes n WHERE 1=1"
                f"{where} ORDER BY n.updated DESC, n.path LIMIT ?", (*args, limit)).fetchall()
        finally:
            conn.close()
        return [hit(r) for r in rows]

    def row(self, rel: str):
        conn = self.connect()
        try:
            return conn.execute("SELECT * FROM notes WHERE path=?", (rel,)).fetchone()
        finally:
            conn.close()

    def counts(self) -> dict:
        conn = self.connect()
        try:
            return {r["pool"]: r["c"] for r in conn.execute(
                "SELECT pool, count(*) AS c FROM notes GROUP BY pool")}
        finally:
            conn.close()


def hit(r, score: float | None = None) -> dict:
    out = {k: r[k] for k in ("path", "pool", "title", "actor", "kind", "updated")}
    out["tags"] = json.loads(r["tags"] or "[]")
    out["snippet"] = " ".join(str(r["snippet"] or "").split())
    if "attributed" in r.keys():
        out["attributed"] = bool(r["attributed"])
    if score is not None:
        out["score"] = round(score, 6)
    return out


def fuse(lex: list, vec: list, limit: int) -> list:
    """Reciprocal rank fusion of the lexical and the vector ranking (one list: its order)."""
    score, rows = {}, {}
    for ranking in (lex, vec):
        for i, r in enumerate(ranking):
            score[r["path"]] = score.get(r["path"], 0.0) + 1.0 / (RRF_K + i + 1)
            rows.setdefault(r["path"], r)
    best = sorted(score, key=lambda p: (-score[p], p))[:limit]
    return [hit(rows[p], score[p]) for p in best]
