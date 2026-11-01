"""`board init/start/status/stop/tokens`, `project`, `version` as subprocesses."""
from __future__ import annotations

import json
import sqlite3
import stat

from konstant.board import auth

ROLES = ("owner", "orchestrator", "worker", "verifier", "viewer")
IDENTITIES = ("planner", "dod-reviewer", "scenario", "factory")    # docs/LEVEL5.md 2.2


def test_init_mints_role_and_identity_tokens_private_and_stores_only_hashes(fresh):
    fresh.ok("board", "init")
    secrets = fresh.home / "var" / "secrets"
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o700
    files = sorted(p.name for p in secrets.iterdir())
    assert files == sorted(f"{r}.token" for r in ROLES + IDENTITIES)
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in secrets.iterdir())
    db = fresh.home / "var" / "board.db"
    conn = sqlite3.connect(db)
    assert conn.execute("select count(*) from tokens").fetchone()[0] == 9
    conn.close()
    raw = b"".join(p.read_bytes() for p in db.parent.glob("board.db*"))
    for p in secrets.iterdir():
        token = p.read_text().strip()
        assert len(token) >= 40 and token.encode() not in raw
        assert auth.sha256(token).encode() in raw


def test_init_twice_keeps_tokens(fresh):
    fresh.ok("board", "init")
    before = {p.name: p.read_text() for p in (fresh.home / "var" / "secrets").iterdir()}
    out = fresh.ok("--json", "board", "init").stdout
    assert set(json.loads(out)["tokens"].values()) == {"kept"}
    after = {p.name: p.read_text() for p in (fresh.home / "var" / "secrets").iterdir()}
    assert before == after


def test_status_and_unreachable_board(fresh):
    fresh.ok("board", "init")
    res = fresh.run("board", "status")
    assert res.returncode == 1 and "down" in res.stdout
    res = fresh.run("job", "list")
    assert res.returncode == 1 and "board unreachable" in res.stderr


def test_board_refuses_to_start_on_a_malformed_policy(fresh):
    fresh.ok("board", "init")
    with open(fresh.home / "konstant.toml", "a") as fh:
        fh.write('[board.policy]\nverify_roles = ["verifer"]\n')
    res = fresh.run("board", "start")
    assert res.returncode == 1 and "unknown role" in res.stderr
    assert not (fresh.home / "var" / "board.pid").exists()


def test_running_board(ws):
    assert "running" in ws.ok("board", "status").stdout
    assert "already running" in ws.ok("board", "start").stdout
    assert ws.ok("version").stdout.strip() == "konstant 0.1.0"
    projects = json.loads(ws.ok("project", "list", "--json").stdout)
    assert [p["slug"] for p in projects] == ["demo"]
    assert (ws.home / "projects" / "demo").is_dir()


def test_tokens_list_and_rotate(ws):
    res = ws.run("--as", "orchestrator", "board", "tokens")
    assert res.returncode == 1 and "requires role owner" in res.stderr
    listing = ws.ok("--as", "owner", "board", "tokens").stdout
    assert "viewer" in listing and "label=" in listing
    path = ws.home / "var" / "secrets" / "viewer.token"
    old = path.read_text()
    ws.ok("--as", "owner", "board", "tokens", "--rotate", "viewer")
    assert path.read_text() != old and stat.S_IMODE(path.stat().st_mode) == 0o600
    ws.ok("--as", "viewer", "job", "list")


def test_project_add_init_git(ws):
    ws.ok("project", "add", "gitted", "--init-git")
    assert (ws.home / "projects" / "gitted" / ".git").is_dir()
    res = ws.run("project", "add", "gitted")
    assert res.returncode == 1 and "already exists" in res.stderr
