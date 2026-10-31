"""Versioned schema migrator: applies migrations/NNNN_*.sql above schema_meta.version, in order.

Each migration runs in one transaction and ends by setting schema_meta.version to its number,
so a half-applied migration never leaves the version claiming it is done.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from konstant.board import db

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def available(directory: Path = MIGRATIONS_DIR) -> list:
    out = []
    for p in sorted(directory.iterdir()):
        m = _NAME.match(p.name)
        if m:
            out.append((int(m.group(1)), p))
    return out


def target_version(directory: Path = MIGRATIONS_DIR) -> int:
    found = available(directory)
    return found[-1][0] if found else 0


def current_version(path: Path) -> int:
    if not Path(path).exists():
        return 0
    with db.reading(path) as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND "
                           "name='schema_meta'").fetchone()
        if row is None:
            return 0
        return int(conn.execute("SELECT version FROM schema_meta").fetchone()[0])


def private(path: Path) -> None:
    """The DB and its WAL/SHM files are 0600 (REVIEW F-14, F-25); SQLite gives a new WAL/SHM the
    database file's own mode."""
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            os.chmod(p, 0o600)


def migrate(path: Path, directory: Path = MIGRATIONS_DIR) -> list:
    """Bring the DB at `path` to the newest schema. Returns the versions applied."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():           # created private: briefs, evidence and trail are not public
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    private(path)
    conn = db.connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    finally:
        conn.close()
    private(path)
    have, applied = current_version(path), []
    for version, sql_file in available(directory):
        if version <= have:
            continue
        conn = db.connect(path)
        try:
            conn.executescript("BEGIN IMMEDIATE;\n" + sql_file.read_text(encoding="utf-8")
                               + f"\nUPDATE schema_meta SET version = {version};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        applied.append(version)
    return applied
