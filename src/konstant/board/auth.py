"""Bearer-token auth: one token per role, only its sha256 stored (DESIGN §5).

`konstant board init` mints `secrets.token_urlsafe(32)` per role into var/secrets/<role>.token
(file 0600, dir 0700) and stores the sha256 in `tokens`. The server maps a presented token to
(label, role). `viewer` reads; every write refuses it.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from pathlib import Path

from konstant.board.policy import ROLES


def sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def lookup(conn: sqlite3.Connection, token: str):
    """(label, role) for an active token, else None."""
    if not token:
        return None
    row = conn.execute("SELECT label, role FROM tokens WHERE sha256=? AND active=1",
                       (sha256(token),)).fetchone()
    return (row["label"], row["role"]) if row else None


def token_file(secrets_dir: Path, role: str) -> Path:
    return Path(secrets_dir) / f"{role}.token"


def _write_secret(path: Path, value: str) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def ensure_secrets_dir(secrets_dir: Path) -> None:
    Path(secrets_dir).mkdir(parents=True, exist_ok=True)
    os.chmod(secrets_dir, 0o700)


def read_token(secrets_dir: Path, role: str) -> str:
    return token_file(secrets_dir, role).read_text(encoding="utf-8").strip()


def mint_missing(conn: sqlite3.Connection, secrets_dir: Path) -> dict:
    """Make sure every role has a token file whose hash is active in the DB.

    Idempotent: an existing token file is kept (its hash is registered if the DB lacks it), so
    re-running init never changes a token. Returns {role: "minted"|"registered"|"kept"}.
    """
    ensure_secrets_dir(secrets_dir)
    out = {}
    for role in ROLES:
        path = token_file(secrets_dir, role)
        if path.is_file() and path.read_text(encoding="utf-8").strip():
            os.chmod(path, 0o600)
            digest = sha256(read_token(secrets_dir, role))
            row = conn.execute("SELECT active FROM tokens WHERE sha256=?", (digest,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO tokens (role, label, sha256) VALUES (?,?,?)",
                             (role, role, digest))
                out[role] = "registered"
            else:
                out[role] = "kept"
            continue
        value = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO tokens (role, label, sha256) VALUES (?,?,?)",
                     (role, role, sha256(value)))
        _write_secret(path, value)
        out[role] = "minted"
    return out


def rotate(conn: sqlite3.Connection, role: str, label: str | None = None) -> str:
    """Deactivate every active token of `role` and insert a new one. Returns the plaintext."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    value = secrets.token_urlsafe(32)
    conn.execute("UPDATE tokens SET active=0 WHERE role=? AND label=? AND active=1",
                 (role, label or role))
    conn.execute("INSERT INTO tokens (role, label, sha256) VALUES (?,?,?)",
                 (role, label or role, sha256(value)))
    return value


def write_token(secrets_dir: Path, role: str, value: str) -> None:
    ensure_secrets_dir(secrets_dir)
    _write_secret(token_file(secrets_dir, role), value)
