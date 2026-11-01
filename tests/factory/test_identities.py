"""Factory identities on the board (docs/LEVEL5.md 2.2, wave L5-2): `board init` mints one token
per identity, the board compares LABELS and refuses the identity pairs that must differ, and a
phase's client uses only the token of its own identity. TestClient against a migrated DB.

  B6  approve with the requester's own label -> 403 `the requester cannot approve its own DoD`
  B7  the dod-reviewer tries `claim` -> 403 `the DoD reviewer of a job cannot claim it`
Each refusal has a _red test (the guard taken out: the forbidden pair goes through) beside it."""
from __future__ import annotations

import pytest

from konstant.board import db
from konstant.board.api import lifecycle
from konstant.board.policy import IDENTITIES
from tests.board.conftest import Board


@pytest.fixture()
def board(tmp_path):
    (tmp_path / "konstant.toml").write_text("")
    return Board(tmp_path)


def filed(b: Board, who="orchestrator", approval=True) -> int:
    res = b.add(who, approval=approval)
    assert res.status_code == 200, res.text
    return res.json()["id"]


# --- tokens -----------------------------------------------------------------------------------

def test_init_mints_every_identity_with_its_label_and_role(board):
    with db.reading(board.cfg.db_path) as conn:
        rows = {r["label"]: r["role"] for r in conn.execute(
            "SELECT label, role FROM tokens WHERE active=1")}
    assert {k: rows[k] for k in IDENTITIES} == IDENTITIES
    for label, role in IDENTITIES.items():
        who = board.call(label, "GET", "/api/whoami").json()
        assert who == {"label": label, "role": role}


def test_rotate_a_label_green_and_a_foreign_label_red(board):
    old = board.tokens["scenario"]
    res = board.call("owner", "POST", "/api/tokens/rotate", {"role": "worker",
                                                             "label": "scenario"})
    assert res.status_code == 200 and res.json()["label"] == "scenario"
    assert board.client.get("/api/whoami", headers={"Authorization": f"Bearer {old}"}
                            ).status_code == 401
    assert board.call("worker", "GET", "/api/whoami").status_code == 200   # worker untouched
    bad = board.call("owner", "POST", "/api/tokens/rotate", {"role": "orchestrator",
                                                             "label": "planner"})
    assert bad.status_code == 422 and "not a orchestrator label" in bad.json()["detail"]


# --- B6: the requester never approves its own DoD ---------------------------------------------

def test_B6_requester_approving_its_own_dod_red(board):
    jid = filed(board, "owner")
    res = board.call("owner", "POST", f"/api/jobs/{jid}/approve")
    assert res.status_code == 403, res.text
    assert "the requester cannot approve its own DoD" in res.json()["detail"]
    assert board.status(jid) == "waiting_approval"


def test_B6_another_identity_approves_green(board):
    jid = filed(board, "orchestrator")
    res = board.call("owner", "POST", f"/api/jobs/{jid}/approve")
    assert res.status_code == 200 and res.json()["status"] == "queued"


def test_B6_owner_role_with_the_requesters_label_red(board):
    """The guard compares labels, not roles: an owner-role token labelled `planner` (the label
    that filed the job) cannot approve it."""
    jid = filed(board, "planner")
    tok = board.add_token("owner", "planner")
    res = board.call(tok, "POST", f"/api/jobs/{jid}/approve")
    assert res.status_code == 403 and "cannot approve its own DoD" in res.text


# --- B7: the DoD reviewer and the scenario writer never claim or close ------------------------

def review(b: Board, jid: int, who="dod-reviewer", word="SHIP"):
    return b.call(who, "POST", f"/api/jobs/{jid}/dod-review", {"verdict": word, "reason": "ok"})


def test_dod_review_only_from_the_dod_reviewer_identity(board):
    jid = filed(board, "planner")
    for who in ("worker", "orchestrator", "owner", "scenario"):
        res = review(board, jid, who)
        assert res.status_code == 403 and "dod-reviewer identity" in res.text, (who, res.text)
    assert review(board, jid, word="MAYBE").status_code == 422
    res = review(board, jid)
    assert res.status_code == 200, res.text
    trail = board.call("viewer", "GET", f"/api/jobs/{jid}/trail").json()["trail"]
    assert [(t["actor"], t["kind"]) for t in trail][-1] == ("dod-reviewer", "dod-review")
    own = filed(board, "dod-reviewer")
    assert review(board, own).status_code == 403          # never on a job it filed


def test_B7_dod_reviewer_claiming_red(board):
    jid = filed(board, "planner", approval=False)
    assert review(board, jid).status_code == 200
    tok = board.add_token("worker", "dod-reviewer-2")     # sanity: another worker label claims
    res = board.call("dod-reviewer", "POST", f"/api/jobs/{jid}/claim")
    assert res.status_code == 403, res.text
    assert "the DoD reviewer of a job cannot claim it" in res.json()["detail"]
    assert board.status(jid) == "queued"
    assert board.call(tok, "POST", f"/api/jobs/{jid}/claim").status_code == 200


def test_B7_red_twin_without_the_guard_the_reviewer_claims(board, monkeypatch):
    jid = filed(board, "planner", approval=False)
    assert review(board, jid).status_code == 200
    monkeypatch.setattr(lifecycle, "identity_guard", lambda *a, **k: None)
    assert board.call("dod-reviewer", "POST", f"/api/jobs/{jid}/claim").status_code == 200


def test_scenario_writer_cannot_claim_or_close_red_and_worker_can_green(board):
    jid = filed(board, "planner", approval=False)
    pair = [{"hid": "H1", "kind": "proof", "sha256": "1" * 64}]
    assert board.call("worker", "POST", f"/api/jobs/{jid}/holdouts",
                      {"holdouts": pair}).status_code == 403      # a plain worker never seals
    res = board.call("scenario", "POST", f"/api/jobs/{jid}/holdouts", {"holdouts": pair})
    assert res.status_code == 200, res.text
    assert res.json()["holdouts"][0]["author_label"] == "scenario"
    with db.transaction(board.cfg.db_path) as conn:      # level-4 claim path for this check
        conn.execute("UPDATE jobs SET holdout_required=0 WHERE id=?", (jid,))
    res = board.call("scenario", "POST", f"/api/jobs/{jid}/claim")
    assert res.status_code == 403 and "the scenario writer of a job cannot claim it" in res.text
    assert board.call("worker", "POST", f"/api/jobs/{jid}/claim").status_code == 200
    with db.transaction(board.cfg.db_path) as conn:
        conn.execute("UPDATE jobs SET assignee='scenario' WHERE id=?", (jid,))
    res = board.call("scenario", "POST", f"/api/jobs/{jid}/close",
                     {"verify_cmd": "pytest -q", "verify_exit": 0, "verify_output": "1 passed"})
    assert res.status_code == 403 and "the scenario writer of a job cannot close it" in res.text


def test_scenario_label_with_a_foreign_role_cannot_seal(board):
    """`scenario` seals only as the worker-role identity: a viewer token labelled scenario is
    read-only, and an orchestrator token labelled scenario is not the identity either."""
    jid = filed(board, "planner", approval=False)
    pair = [{"hid": "H1", "kind": "proof", "sha256": "1" * 64}]
    tok = board.add_token("orchestrator", "scenario")
    res = board.call(tok, "POST", f"/api/jobs/{jid}/holdouts", {"holdouts": pair})
    assert res.status_code == 403, res.text
