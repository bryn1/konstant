"""The board side of holdouts (docs/LEVEL5.md 2.5, 3.2, 3.5, 3.6): commitments only, the claim
guard (A11), the PASS guard, a LEAK burns the set, the exposure budget retires a worn set and a
second worn set blocks the job. TestClient against a migrated DB."""
from __future__ import annotations

import json
import sqlite3

import pytest

from konstant.board import db, migrate
from konstant.verify.holdout import digest
from tests.board.conftest import Board

SHA1, SHA2, SHA3 = "1" * 64, "2" * 64, "3" * 64
PAIR = [{"hid": "H1", "kind": "proof", "sha256": SHA1},
        {"hid": "H2", "kind": "regression", "sha256": SHA2}]


@pytest.fixture()
def board(tmp_path):
    (tmp_path / "konstant.toml").write_text("")
    b = Board(tmp_path, policy={"max_rounds": 10})
    return b


def job(b: Board, status="queued", required=True) -> int:
    jid = b.insert_job(status, type="code")
    with db.transaction(b.cfg.db_path) as conn:
        conn.execute("UPDATE jobs SET holdout_required=? WHERE id=?", (int(required), jid))
    return jid


def seal(b, jid, rows=PAIR, who="owner"):
    return b.call(who, "POST", f"/api/jobs/{jid}/holdouts", {"holdouts": rows})


def to_state(b, jid, status, closed_by="worker"):
    with db.transaction(b.cfg.db_path) as conn:
        conn.execute("UPDATE jobs SET status=?, closed_by=? WHERE id=?", (status, closed_by, jid))


def verdict(b, jid, word, holdout=None, who="verifier"):
    body = {"verdict": word, "reason": "r"}
    if holdout is not None:
        body["holdout"] = holdout
    return b.call(who, "POST", f"/api/jobs/{jid}/verdict", body)


def payload(b, jid, passed=(True, True), **kw):
    rows = [r for r in b.call("viewer", "GET", f"/api/jobs/{jid}/holdouts").json()["holdouts"]
            if r["state"] == "sealed"]
    out = {"rows": [{"hid": r["hid"], "passed": p} for r, p in zip(rows, passed)],
           "digest": digest(rows), "generation": rows[0]["generation"] if rows else None,
           "leak": False, "failed_round": not all(passed)}
    out.update(kw)
    return out


def test_seal_green_stores_commitments_only(board):
    jid = job(board)
    res = seal(board, jid)
    assert res.status_code == 200, res.text
    got = board.call("viewer", "GET", f"/api/jobs/{jid}/holdouts").json()
    assert got["count"] == 2 and got["sealed"] == 2 and got["holdout_required"] is True
    assert set(got["holdouts"][0]) == {"hid", "kind", "sha256", "state", "sealed_at",
                                       "author_label", "generation", "trail_id"}
    trail = board.call("viewer", "GET", f"/api/jobs/{jid}/trail").json()["trail"]
    assert trail[-1]["kind"] == "holdout" and "sealed H1, H2" in trail[-1]["body"]
    cols = {r[1] for r in sqlite3.connect(board.cfg.db_path).execute(
        "PRAGMA table_info(holdouts)")}
    assert not cols & {"run", "expect", "hint", "canary", "content", "body"}


@pytest.mark.parametrize("who,state,rows,code", [
    ("orchestrator", "queued", PAIR, 403), ("worker", "queued", PAIR, 403),
    ("owner", "claimed", PAIR, 409), ("owner", "completed_unverified", PAIR, 409),
    ("owner", "queued", [{"hid": "H1", "kind": "proof", "sha256": "xyz"}], 422),
    ("owner", "queued", [{"hid": "1", "kind": "proof", "sha256": SHA1}], 422),
    ("owner", "queued", [PAIR[0], PAIR[0]], 409)])
def test_seal_red(board, who, state, rows, code):
    jid = job(board, state)
    assert seal(board, jid, rows, who).status_code == code


def test_seal_red_a_used_id_or_a_changed_commitment(board):
    jid = job(board)
    seal(board, jid)
    assert seal(board, jid, [{"hid": "H2", "kind": "proof", "sha256": SHA3}]).status_code == 409
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        with db.transaction(board.cfg.db_path) as conn:
            conn.execute("UPDATE holdouts SET sha256=? WHERE job_id=?", (SHA3, jid))
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        with db.transaction(board.cfg.db_path) as conn:
            conn.execute("DELETE FROM holdouts")


def test_claim_guard_red_no_holdout_sealed(board):
    jid = job(board)
    res = board.call("worker", "POST", f"/api/jobs/{jid}/claim")
    assert res.status_code == 409 and "no holdout sealed" in res.json()["detail"]
    seal(board, jid, PAIR[:1])
    assert board.call("worker", "POST", f"/api/jobs/{jid}/claim").status_code == 409


def git_project(b: Board):
    """The project as a git repository with one commit: a holdout job's first claim records
    its job clone from the target's commit (docs/LEVEL5.md 2.4, L5-2)."""
    import subprocess
    d = b.cfg.home / "projects" / "demo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "README.md").write_text("demo\n")
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c",
                                                  "user.email=t@example.com", "commit", "-qm", "b"]):
        subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True)


def test_claim_guard_green(board):
    git_project(board)
    jid = job(board)
    seal(board, jid)
    assert board.call("worker", "POST", f"/api/jobs/{jid}/claim").status_code == 200
    plain = job(board, required=False)            # a level-4 job is not affected
    assert board.call("worker", "POST", f"/api/jobs/{plain}/claim").status_code == 200


def test_pass_guard_red(board):
    jid = job(board)
    seal(board, jid)
    to_state(board, jid, "completed_unverified")
    for h in (None, payload(board, jid, (True, False)), payload(board, jid, digest="0" * 64),
              payload(board, jid, leak=True), {**payload(board, jid), "rows": [
                  {"hid": "H1", "passed": True}]}):
        res = verdict(board, jid, "PASS", h)
        assert res.status_code == 409 and "holdouts" in res.json()["detail"], (h, res.text)
    res = verdict(board, jid, "PASS", payload(board, jid), who="owner")
    assert res.status_code == 200          # the owner too needs the holdout result


def test_pass_guard_green(board):
    jid = job(board)
    seal(board, jid)
    to_state(board, jid, "completed_unverified")
    assert verdict(board, jid, "PASS", payload(board, jid)).status_code == 200
    assert board.status(jid) == "verified"
    v = board.call("viewer", "GET", f"/api/jobs/{jid}").json()["verifications"][-1]
    assert v["holdouts"]["rows"][0]["hid"] == "H1"


def test_leak_burns_the_set_red(board):
    jid = job(board)
    seal(board, jid)
    to_state(board, jid, "completed_unverified")
    res = verdict(board, jid, "BLOCKED", payload(board, jid, leak=True))
    assert res.status_code == 200
    states = {r["state"] for r in board.call("viewer", "GET", f"/api/jobs/{jid}/holdouts")
              .json()["holdouts"]}
    assert states == {"burned"} and board.status(jid) == "completed_unverified"
    assert board.call("worker", "POST", f"/api/jobs/{jid}/claim").status_code == 409


def test_worn_set_is_retired_then_a_second_worn_set_blocks(board):
    jid = job(board)
    seal(board, jid)
    for rnd in (1, 2):
        to_state(board, jid, "completed_unverified")
        assert verdict(board, jid, "FAIL", payload(board, jid, (False, True))).status_code == 200
    rows = board.call("viewer", "GET", f"/api/jobs/{jid}/holdouts").json()["holdouts"]
    assert {r["state"] for r in rows} == {"retired"} and board.status(jid) == "queued"
    claim = board.call("worker", "POST", f"/api/jobs/{jid}/claim")
    assert claim.status_code == 409 and "no holdout sealed" in claim.json()["detail"]
    fresh = [{"hid": "H3", "kind": "proof", "sha256": SHA3},
             {"hid": "H4", "kind": "regression", "sha256": "4" * 64}]
    assert seal(board, jid, fresh).json()["holdouts"][0]["generation"] == 2
    for rnd in (1, 2):
        to_state(board, jid, "completed_unverified")
        verdict(board, jid, "FAIL", payload(board, jid, (False, True)))
    assert board.status(jid) == "blocked"
    trail = board.call("viewer", "GET", f"/api/jobs/{jid}/trail").json()["trail"]
    assert any("second holdout set is worn" in t["body"] for t in trail)


def test_a_fail_not_caused_by_holdouts_spends_no_exposure(board):
    jid = job(board)
    seal(board, jid)
    for _ in (1, 2, 3):
        to_state(board, jid, "completed_unverified")
        verdict(board, jid, "FAIL", payload(board, jid))
    assert {r["state"] for r in board.call("viewer", "GET", f"/api/jobs/{jid}/holdouts")
            .json()["holdouts"]} == {"sealed"}


def test_migration_from_v1_keeps_the_trail_and_its_guards(tmp_path):
    v1 = tmp_path / "mig"
    v1.mkdir()
    (v1 / "0001_init.sql").write_text((migrate.MIGRATIONS_DIR / "0001_init.sql").read_text())
    path = tmp_path / "b.db"
    assert migrate.migrate(path, v1) == [1]
    with db.transaction(path) as conn:
        conn.execute("INSERT INTO projects (slug, name, path) VALUES ('d', 'd', 'd')")
        conn.execute("INSERT INTO jobs (project_id, type, title, status, requested_by) "
                     "VALUES (1, 'code', 't', 'queued', 'x')")
        conn.execute("INSERT INTO trail (job_id, actor, role, kind, body) VALUES "
                     "(1, 'x', 'owner', 'note', 'kept')")
    assert migrate.migrate(path) == [2, 3]
    with db.transaction(path) as conn:
        assert conn.execute("SELECT body FROM trail").fetchone()[0] == "kept"
        assert conn.execute("SELECT holdout_required FROM jobs").fetchone()[0] == 0
        conn.execute("INSERT INTO trail (job_id, actor, role, kind) VALUES (1, 'x', 'owner', "
                     "'holdout')")
    for sql in ("UPDATE trail SET body='x'", "DELETE FROM trail"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            with db.transaction(path) as conn:
                conn.execute(sql)
    assert json.dumps(migrate.current_version(path)) == "3"
