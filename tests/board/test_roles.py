"""Role separation: the closer cannot verify, the viewer cannot write, tokens are per role."""
from __future__ import annotations

import pytest

from tests.board.conftest import GOOD_EVIDENCE


def _closed_by(board, closer_role: str) -> int:
    job = board.insert_job("claimed", requested_by=closer_role, assignee=closer_role)
    res = board.call(closer_role, "POST", f"/api/jobs/{job}/close", GOOD_EVIDENCE)
    assert res.status_code == 200, res.text
    return job


def test_closer_cannot_verify(board):
    # the owner closes, then the same identity posts the verdict: refused although owner may verify
    job = _closed_by(board, "owner")
    res = board.call("owner", "POST", f"/api/jobs/{job}/verdict", {"verdict": "PASS"})
    assert res.status_code == 403
    assert "the closer cannot verify" in res.json()["detail"]
    assert board.status(job) == "completed_unverified"
    # an owner-ROLE token whose label is the closer's identity is refused the same way
    job2 = _closed_by(board, "orchestrator")
    disguised = board.add_token("owner", "orchestrator")
    res = board.call(disguised, "POST", f"/api/jobs/{job2}/verdict", {"verdict": "PASS"})
    assert res.status_code == 403 and "the closer cannot verify" in res.json()["detail"]
    # positive control: a different identity with a verify role passes
    res = board.call("verifier", "POST", f"/api/jobs/{job2}/verdict", {"verdict": "PASS"})
    assert res.status_code == 200 and board.status(job2) == "verified"


def test_orchestrator_verdict_names_the_verify_roles(board):
    job = _closed_by(board, "orchestrator")
    res = board.call("orchestrator", "POST", f"/api/jobs/{job}/verdict", {"verdict": "PASS"})
    assert res.status_code == 403
    assert "verifier, owner" in res.json()["detail"]


def test_verified_cannot_be_left(board):
    job = _closed_by(board, "orchestrator")
    assert board.call("verifier", "POST", f"/api/jobs/{job}/verdict",
                      {"verdict": "PASS"}).status_code == 200
    for verb, who in (("reopen", "owner"), ("cancel", "owner"), ("claim", "worker")):
        res = board.call(who, "POST", f"/api/jobs/{job}/{verb}", {"reason": "x"})
        assert res.status_code == 409, verb
    assert board.status(job) == "verified"


WRITES = [("POST", "/api/projects", {"slug": "x"}), ("POST", "/api/jobs", {}),
          ("POST", "/api/jobs/1/trail", {"body": "x"}), ("POST", "/api/tokens/rotate",
                                                         {"role": "viewer"})]


@pytest.mark.parametrize("method,path,body", WRITES)
def test_viewer_is_read_only(board, method, path, body):
    res = board.call("viewer", method, path, body)
    assert res.status_code == 403 and "read-only" in res.json()["detail"]


def test_viewer_reads(board):
    assert board.call("viewer", "GET", "/api/jobs").status_code == 200
    assert board.call("viewer", "GET", f"/api/jobs/{board.root}").status_code == 200
    assert board.call("viewer", "GET", "/api/whoami").json() == {"label": "viewer",
                                                                "role": "viewer"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"},
                                     {"Authorization": "nope"}])
def test_unknown_or_missing_token_is_401(board, headers):
    assert board.client.get("/api/jobs", headers=headers).status_code == 401
    assert board.client.post("/api/projects", json={"slug": "x"},
                             headers=headers).status_code == 401


def test_health_needs_no_token(board):
    assert board.client.get("/health").json()["ok"] is True


def test_trail_kinds_other_than_note_and_finding_are_reserved(board):
    for kind in ("verdict", "status", "evidence"):
        res = board.call("owner", "POST", f"/api/jobs/{board.root}/trail",
                         {"kind": kind, "body": "forged"})
        assert res.status_code == 422 and "reserved" in res.json()["detail"]
    res = board.call("worker", "POST", f"/api/jobs/{board.root}/trail",
                     {"kind": "finding", "body": "real"})
    assert res.status_code == 200


def test_token_admin_is_owner_only_and_never_shows_values(board):
    assert board.call("orchestrator", "GET", "/api/tokens").status_code == 403
    rows = board.call("owner", "GET", "/api/tokens").json()["tokens"]
    assert len(rows) == 5 and all("sha256" not in r and "token" not in r for r in rows)
    old = board.tokens["worker"]
    res = board.call("owner", "POST", "/api/tokens/rotate", {"role": "worker"})
    assert res.status_code == 200
    assert board.client.get("/api/whoami", headers={"Authorization": f"Bearer {old}"}
                            ).status_code == 401
    new = res.json()["token"]
    assert board.client.get("/api/whoami", headers={"Authorization": f"Bearer {new}"}
                            ).json()["role"] == "worker"


def test_project_add_roles(board):
    assert board.call("worker", "POST", "/api/projects", {"slug": "w"}).status_code == 403
    assert board.call("orchestrator", "POST", "/api/projects", {"slug": "o"}).status_code == 200
    assert board.call("owner", "POST", "/api/projects", {"slug": "o"}).status_code == 409
    assert board.call("owner", "POST", "/api/projects", {"slug": "Bad Slug"}).status_code == 422
