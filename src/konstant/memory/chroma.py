"""The optional Chroma vector store (`[memory] engine = "chroma"`; `pip install
'konstant[chroma]'`): the note vectors live in a local, persistent Chroma collection
(`var/memory/chroma/`) instead of the index's own `vec` column. Everything else stays as it is:
the vault is the source of truth, SQLite FTS5 still does lexical recall and holds the catalog of
notes (pool, attribution), and every hit Chroma returns is filtered against that catalog,
so pools and attribution are decided in ONE place (index.py `_scope`). Vectors always come
from the configured local endpoint (embed.py): Chroma's own default embedding would download a
model, and konstant stays offline (config.check_memory refuses chroma without an endpoint).
"""
from __future__ import annotations

import shutil
from pathlib import Path

COLLECTION = "konstant-memory"
EXTRA = "pip install 'konstant[chroma]' (into this workspace's .venv)"


class ChromaMissing(Exception):
    pass


class ChromaVectors:
    def __init__(self, path):
        self.path = Path(path)
        try:
            import chromadb
        except ImportError:
            raise ChromaMissing(f'[memory] engine = "chroma" needs the chromadb package: '
                                f"{EXTRA}") from None
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        settings = chromadb.config.Settings(anonymized_telemetry=False, allow_reset=False)
        self.client = chromadb.PersistentClient(path=str(self.path), settings=settings)
        self.col = self.client.get_or_create_collection(
            COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine"})

    def upsert(self, rows: list) -> None:
        """rows: [(path, vector, pool)]."""
        if rows:
            self.col.upsert(ids=[r[0] for r in rows], embeddings=[list(r[1]) for r in rows],
                            metadatas=[{"pool": r[2]} for r in rows])

    def delete(self, paths: list) -> None:
        if paths:
            self.col.delete(ids=list(paths))

    def query(self, vec: list, k: int, pools=None) -> list:
        """[(path, similarity)] best first; the caller filters against the catalog."""
        n = self.col.count()
        if not n:
            return []
        where = {"pool": {"$in": sorted(pools)}} if pools else None
        res = self.col.query(query_embeddings=[list(vec)], n_results=min(k, n), where=where,
                             include=["distances"])
        ids = (res.get("ids") or [[]])[0]
        dist = (res.get("distances") or [[]])[0]
        return [(p, 1.0 - float(d)) for p, d in zip(ids, dist)]

    @staticmethod
    def drop(path) -> None:
        shutil.rmtree(path, ignore_errors=True)
