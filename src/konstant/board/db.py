"""SQLite access for the board: one connection per unit of work, WAL, foreign keys on."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def transaction(path: Path | str):
    """BEGIN IMMEDIATE ... COMMIT; ROLLBACK on any exception. Yields the connection."""
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@contextmanager
def reading(path: Path | str):
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()
