"""Hierarchy: depth <= 2, full-path display ids, old-form resolution, move validation."""
from __future__ import annotations

import pytest

from konstant.board import db, tree


def test_display_ids_are_full_paths(board):
    a = board.add(title="T: feature a").json()
    b = board.add(title="T: feature b").json()
    task = board.add(title="T: task", parent=str(b["id"])).json()
    assert (a["display_id"], b["display_id"]) == (f"{board.root}.1", f"{board.root}.2")
    assert task["display_id"] == f"{board.root}.2.1" and task["depth"] == 2
    with db.reading(board.cfg.db_path) as conn:
        assert tree.resolve_path(conn, task["display_id"]) == task["id"]
        assert tree.resolve_path(conn, f"{b['id']}.1") == task["id"]       # the one-level form
        for bad in ("1.", ".1", "a.b", "", None, "1.0", "1.99"):
            assert tree.resolve_path(conn, bad) is None, bad
    shown = board.call("viewer", "GET", f"/api/jobs/{task['display_id']}").json()
    assert shown["id"] == task["id"]


def test_depth_above_two_is_refused(board):
    feature = board.add(title="T: feature").json()
    task = board.add(title="T: task", parent=str(feature["id"])).json()
    res = board.add(title="T: too deep", parent=str(task["id"]))
    assert res.status_code == 422 and "depth > 2" in res.json()["detail"]


def test_a_job_without_parent_goes_under_the_project_root(board):
    assert board.add().json()["parent_id"] == board.root


def _move(board, job, parent, reason="restructure"):
    return board.call("owner", "POST", f"/api/jobs/{job}/move", {"parent": str(parent),
                                                                 "reason": reason})


def test_move_rules(board):
    f1 = board.add(title="T: f1").json()["id"]
    f2 = board.add(title="T: f2").json()["id"]
    t1 = board.add(title="T: t1", parent=str(f1)).json()["id"]
    assert _move(board, f1, t1).status_code == 409                       # cycle
    assert _move(board, f1, f2).status_code == 422                       # f1 has a child: depth 3
    assert _move(board, t1, t1).status_code == 409                       # own parent
    assert _move(board, t1, 9999).status_code == 404
    res = _move(board, t1, f2, reason="")
    assert res.status_code == 422 and "reason" in res.json()["detail"]
    board.call("owner", "POST", "/api/projects", {"slug": "other"})
    other_root = board.call("viewer", "GET", "/api/projects").json()["projects"][1]["root_job_id"]
    assert _move(board, t1, other_root).status_code == 409               # another project


def test_move_reports_shifted_siblings_and_is_idempotent(board):
    f1 = board.add(title="T: f1").json()["id"]
    f2 = board.add(title="T: f2").json()["id"]
    a = board.add(title="T: a", parent=str(f1)).json()["id"]
    b = board.add(title="T: b", parent=str(f1)).json()["id"]
    res = _move(board, a, f2).json()
    assert res["display_id"] == f"{board.root}.2.1"
    assert {"id": b, "from": f"{board.root}.1.2", "to": f"{board.root}.1.1"} in res["shifted"]
    assert _move(board, a, f2).json()["noop"] is True
    trail = board.call("viewer", "GET", f"/api/jobs/{a}/trail").json()["trail"]
    assert [t["kind"] for t in trail].count("move") == 1


def test_check_new_child_unknown_parent(board):
    with db.reading(board.cfg.db_path) as conn:
        with pytest.raises(tree.TreeRefused) as exc:
            tree.check_new_child(conn, 4242)
    assert exc.value.code == 404
