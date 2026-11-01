"""Bearer-token auth: one token per label, only its sha256 stored (DESIGN §5).

`konstant board init` mints `secrets.token_urlsafe(32)` per role (label = role) and per factory
identity (docs/LEVEL5.md 2.2: planner, dod-reviewer, scenario as worker; factory as orchestrator)
into var/secrets/<label>.token (file 0600, dir 0700) and stores the sha256 in `tokens`. The server
maps a presented token to (label, role); the board's guards compare labels. `viewer` reads; every
write refuses it.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from pathlib import Path

from konstant.board.policy import IDENTITIES, ROLES, role_of


def sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def lookup(conn: sqlite3.Connection, token: str):
    """(label, role) for an active token, else None."""
    if not token:
        return None
    row = conn.execute("SELECT label, role FROM tokens WHERE sha256=? AND active=1",
                       (sha256(token),)).fetchone()
    return (row["label"], row["role"]) if row else None


def token_file(secrets_dir: Path, label: str) -> Path:
    """var/secrets/<label>.token (a role's own token: label = role)."""
    return Path(secrets_dir) / f"{label}.token"


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
    """Make sure every role and every factory identity has a token file whose hash is active in
    the DB.

    Idempotent: an existing token file is kept (its hash is registered if the DB lacks it), so
    re-running init never changes a token. Returns {label: "minted"|"registered"|"kept"}.
    """
    ensure_secrets_dir(secrets_dir)
    out = {}
    for label, role in [(r, r) for r in ROLES] + list(IDENTITIES.items()):
        path = token_file(secrets_dir, label)
        if path.is_file() and path.read_text(encoding="utf-8").strip():
            os.chmod(path, 0o600)
            digest = sha256(read_token(secrets_dir, label))
            row = conn.execute("SELECT active FROM tokens WHERE sha256=?", (digest,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO tokens (role, label, sha256) VALUES (?,?,?)",
                             (role, label, digest))
                out[label] = "registered"
            else:
                out[label] = "kept"
            continue
        value = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO tokens (role, label, sha256) VALUES (?,?,?)",
                     (role, label, sha256(value)))
        _write_secret(path, value)
        out[label] = "minted"
    return out


def check_label(role: str, label: str | None) -> str:
    """The label a token of `role` may carry: the role itself or a factory identity OF that role
    (a label names one actor; `planner` can never become an orchestrator token)."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    label = label or role
    if role_of(label) != role:
        raise ValueError(f"label {label!r} is not a {role} label (labels of {role}: "
                         + ", ".join([role] + [k for k, v in IDENTITIES.items() if v == role])
                         + ")")
    return label


def rotate(conn: sqlite3.Connection, role: str, label: str | None = None) -> str:
    """Deactivate every active token of (`role`, `label`) and insert a new one. Returns the
    plaintext."""
    label = check_label(role, label)
    value = secrets.token_urlsafe(32)
    conn.execute("UPDATE tokens SET active=0 WHERE role=? AND label=? AND active=1",
                 (role, label or role))
    conn.execute("INSERT INTO tokens (role, label, sha256) VALUES (?,?,?)",
                 (role, label or role, sha256(value)))
    return value


def write_token(secrets_dir: Path, label: str, value: str) -> None:
    ensure_secrets_dir(secrets_dir)
    _write_secret(token_file(secrets_dir, label), value)
