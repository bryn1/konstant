"""Filing and reading jobs over HTTP."""
from __future__ import annotations

import pytest


def test_acceptance_is_required(board):
    res = board.add(brief="Make it nice.")
    assert res.status_code == 422 and "acceptance is required" in res.json()["detail"]
    assert board.call("viewer", "GET", "/api/jobs").json()["jobs"] == []


def test_acceptance_is_lifted_from_the_brief(board):
    job = board.add(brief="Context line.\nDoD: greet() returns hello\n- tests pass").json()
    assert job["acceptance"] == "DoD: greet() returns hello\n- tests pass"
    assert job["status"] == "queued" and job["requested_by"] == "orchestrator"


@pytest.mark.parametrize("jtype,code", [("code", 200), ("design", 200), ("project", 422),
                                        ("hygiene", 422), ("", 422)])
def test_type_must_come_from_the_catalog(board, jtype, code):
    res = board.add(type=jtype)
    assert res.status_code == code, res.text
    if code == 422:
        detail = res.json()["detail"]
        assert "known types: " in detail     # the catalog lists types in classifier order
        listed = detail.split("known types: ", 1)[1].split(", ")
        assert sorted(listed) == sorted(["code", "frontend", "infra", "test", "security",
                                         "review", "research", "docs", "design"])


def test_type_from_a_title_tag(board):
    assert board.add(title="[type:research] compare X and Y", type="").json()["type"] == "research"


def test_approval_files_as_waiting_approval(board):
    job = board.add(approval=True).json()
    assert job["status"] == "waiting_approval" and job["approval_required"] is True
    res = board.call("owner", "POST", f"/api/jobs/{job['id']}/approve")
    assert res.json()["status"] == "queued"


def test_unknown_project_parent_and_after(board):
    assert board.add(project="nope").status_code == 404
    assert board.add(parent="999").status_code == 404
    assert board.add(after="999").status_code == 404
    assert board.add(priority=7).status_code == 422


def test_list_filters_and_roots(board):
    a = board.add(title="T: alpha", type="code").json()
    board.add(title="T: beta", type="docs")
    board.call("worker", "POST", f"/api/jobs/{a['id']}/claim")
    jobs = board.call("viewer", "GET", "/api/jobs").json()["jobs"]
    assert [j["title"] for j in jobs] == ["T: alpha", "T: beta"]                 # no root
    assert len(board.call("viewer", "GET", "/api/jobs?roots=true").json()["jobs"]) == 3
    assert [j["title"] for j in board.call("viewer", "GET", "/api/jobs?status=claimed"
                                           ).json()["jobs"]] == ["T: alpha"]
    assert [j["title"] for j in board.call("viewer", "GET", "/api/jobs?type=docs"
                                           ).json()["jobs"]] == ["T: beta"]


def test_search(board):
    board.add(title="T: rate limiter", brief="Token bucket.\nDoD: tests pass")
    done = board.add(title="T: rate report").json()
    board.call("owner", "POST", f"/api/jobs/{done['id']}/cancel", {"reason": "dup"})
    hits = board.call("viewer", "GET", "/api/search?q=rate").json()["jobs"]
    assert len(hits) == 2
    hits = board.call("viewer", "GET", "/api/search?q=rate&open=true").json()["jobs"]
    assert [h["title"] for h in hits] == ["T: rate limiter"]
    assert board.call("viewer", "GET", "/api/search?q=bucket%25").json()["jobs"] == []
    assert board.call("viewer", "GET", "/api/search?q=+").status_code == 422


def test_show_is_untruncated_with_trail(board):
    long_brief = "x" * 5000 + "\nDoD: done"
    job = board.add(brief=long_brief).json()
    shown = board.call("viewer", "GET", f"/api/jobs/{job['id']}?trail=true").json()
    assert shown["brief"] == long_brief
    assert shown["trail"][0]["kind"] == "status" and "filed" in shown["trail"][0]["body"]
    assert board.call("viewer", "GET", "/api/jobs/77").status_code == 404


def test_catalog_route_and_static_view(board):
    cat = board.client.get("/api/catalog").json()
    assert cat["types"]["code"]["agent"] == "coder" and "docs" in cat["review_types"]
    page = board.client.get("/")
    assert page.status_code == 200 and "konstant board" in page.text
    assert board.client.get("/static/board.js").status_code == 200
