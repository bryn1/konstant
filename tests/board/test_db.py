"""Schema, migrator and token storage: invariants the DB itself holds."""
from __future__ import annotations

import sqlite3

import pytest

from konstant.board import auth, db, migrate


def test_migrate_is_idempotent(board):
    assert migrate.current_version(board.cfg.db_path) == migrate.target_version() == 4
    assert migrate.migrate(board.cfg.db_path) == []


def test_acceptance_is_immutable(board):
    job = board.add().json()["id"]
    with pytest.raises(sqlite3.IntegrityError, match="acceptance is immutable"):
        with db.transaction(board.cfg.db_path) as conn:
            conn.execute("UPDATE jobs SET acceptance='DoD: nothing' WHERE id=?", (job,))
    with db.transaction(board.cfg.db_path) as conn:          # other columns still update
        conn.execute("UPDATE jobs SET priority=1 WHERE id=?", (job,))


def test_trail_is_append_only_and_jobs_are_never_deleted(board):
    job = board.add().json()["id"]
    for sql in ("UPDATE trail SET body='x'", "DELETE FROM trail", f"DELETE FROM jobs WHERE id={job}"):
        with pytest.raises(sqlite3.IntegrityError):
            with db.transaction(board.cfg.db_path) as conn:
                conn.execute(sql)


@pytest.mark.parametrize("terminal", ["verified", "reviewed"])
def test_terminal_status_is_final_in_the_db(board, terminal):
    job = board.insert_job(terminal)
    with pytest.raises(sqlite3.IntegrityError, match="terminal"):
        with db.transaction(board.cfg.db_path) as conn:
            conn.execute("UPDATE jobs SET status='queued' WHERE id=?", (job,))


def test_tokens_store_only_hashes(board):
    raw = board.cfg.db_path.read_bytes()
    for suffix in ("-wal", "-shm"):
        p = board.cfg.db_path.with_name(board.cfg.db_path.name + suffix)
        raw += p.read_bytes() if p.exists() else b""
    for token in board.tokens.values():
        assert token.encode() not in raw
    with db.reading(board.cfg.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0] == 9   # 5 roles + 4 identities


def test_token_files_are_private(board):
    d = board.cfg.secrets_dir
    assert oct(d.stat().st_mode & 0o777) == "0o700"
    names = sorted(p.name for p in d.iterdir())
    assert names == sorted(f"{r}.token" for r in board.tokens)
    assert all(oct(p.stat().st_mode & 0o777) == "0o600" for p in d.iterdir())


def test_mint_is_idempotent_and_keeps_existing_tokens(board):
    before = dict(board.tokens)
    with db.transaction(board.cfg.db_path) as conn:
        assert set(auth.mint_missing(conn, board.cfg.secrets_dir).values()) == {"kept"}
    assert {r: auth.read_token(board.cfg.secrets_dir, r) for r in before} == before


def test_a_kept_token_file_is_registered_in_a_fresh_db(board, tmp_path):
    fresh = tmp_path / "fresh.db"
    migrate.migrate(fresh)
    with db.transaction(fresh) as conn:
        states = auth.mint_missing(conn, board.cfg.secrets_dir)
    assert set(states.values()) == {"registered"}
    with db.reading(fresh) as conn:
        assert auth.lookup(conn, board.tokens["verifier"]) == ("verifier", "verifier")


def test_lookup_ignores_revoked_tokens(board):
    with db.transaction(board.cfg.db_path) as conn:
        conn.execute("UPDATE tokens SET active=0 WHERE role='worker'")
    with db.reading(board.cfg.db_path) as conn:
        assert auth.lookup(conn, board.tokens["worker"]) is None
        assert auth.lookup(conn, "") is None
