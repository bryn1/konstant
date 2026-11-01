"""The job state machine, enumerated over EVERY (state, verb, role) triple (DESIGN §4.2).

The expected outcome of each triple comes from SPEC below, written from the design table by
hand - never from konstant.board.transitions - so a drift in the code goes red here instead of
being agreed with. test_table_matches_spec pins the code table to the same spec.
"""
from __future__ import annotations

import itertools

import pytest

from konstant.board import db, transitions
from konstant.board.policy import Policy
from tests.board.conftest import GOOD_EVIDENCE

STATES = ("queued", "waiting_approval", "claimed", "blocked", "completed_unverified",
          "verified", "reviewed", "cancelled")
ROLES = ("owner", "orchestrator", "worker", "verifier", "viewer")
VERBS = ("approve", "claim", "block", "close", "review", "verdict", "reopen", "cancel", "move")

# verb -> roles that may use it (default policy)
SPEC_ROLES = {
    "approve": {"owner"},
    "claim": {"orchestrator", "worker"},
    "block": {"owner", "orchestrator", "worker"},
    "close": {"owner", "orchestrator", "worker"},
    "review": {"owner", "orchestrator", "verifier"},
    "verdict": {"verifier", "owner"},
    "reopen": {"owner", "orchestrator"},
    "cancel": {"owner", "orchestrator"},
    "move": {"owner", "orchestrator"},
}
# (state, verb) -> resulting state; absent = illegal (409)
SPEC_LEGAL = {
    ("waiting_approval", "approve"): "queued",
    ("queued", "claim"): "claimed",
    ("blocked", "claim"): "claimed",
    ("claimed", "block"): "blocked",
    ("claimed", "close"): "completed_unverified",
    ("claimed", "review"): "reviewed",
    ("completed_unverified", "review"): "reviewed",
    ("completed_unverified", "verdict"): "verified",          # a PASS verdict
    ("completed_unverified", "reopen"): "queued",
    ("blocked", "reopen"): "queued",
    ("cancelled", "reopen"): "queued",
    **{(s, "cancel"): "cancelled" for s in ("queued", "waiting_approval", "claimed", "blocked",
                                           "completed_unverified")},
    **{(s, "move"): s for s in STATES},
}

BODIES = {
    "block": {"reason": "waiting on input"},
    "reopen": {"reason": "needs another pass"},
    "cancel": {"reason": "superseded"},
    "close": GOOD_EVIDENCE,
    "review": {"verdict": "findings...\n# VERDICT: SHIP\n", "done": "| R1 | done | PASS | x |"},
    "verdict": {"verdict": "PASS"},
}


def expected(state, verb, role):
    if role not in SPEC_ROLES[verb]:
        return 403, None
    if (state, verb) not in SPEC_LEGAL:
        return 409, None
    return 200, SPEC_LEGAL[(state, verb)]


CASES = [(s, v, r, *expected(s, v, r)) for s, v, r in itertools.product(STATES, VERBS, ROLES)]


def _case_id(case):
    s, v, r, code, _ = case
    kind = {200: "legal", 403: "role", 409: "illegal"}[code]
    return f"{kind}-{s}-{v}-{r}"


def test_enumeration_covers_every_triple():
    assert len(CASES) == len(STATES) * len(VERBS) * len(ROLES) == 360
    assert {(s, v, r) for s, v, r, *_ in CASES} == set(itertools.product(STATES, VERBS, ROLES))
    assert sum(1 for c in CASES if c[3] == 409) >= 20


def test_table_matches_spec():
    assert transitions.STATES == STATES
    assert set(transitions.VERBS) == set(VERBS)
    pol = Policy()
    for verb in VERBS:
        assert set(transitions.roles_for(verb, pol)) == SPEC_ROLES[verb], verb
        rule = transitions.RULES[verb]
        legal_from = {s for (s, v) in SPEC_LEGAL if v == verb}
        assert set(rule.sources) == legal_from, verb


def _job_in(board, state, role, verb=""):
    """The job is the acting role's own (close needs that), except for review and approve: a
    review comes from another identity than the requester/assignee/closer (its own guard,
    tests/review), and the requester never approves its own DoD (docs/LEVEL5.md 2.2, L5-2)."""
    feature = board.insert_job("queued", title="feature")
    mine = "someone-else" if verb in ("review", "approve") else role
    return board.insert_job(state, parent=feature, requested_by=mine, assignee=mine,
                            closed_by="someone-else")


def _run(board, state, verb, role):
    job = _job_in(board, state, role, verb)
    body = dict(BODIES.get(verb, {}))
    if verb == "move":
        body = {"parent": str(board.root), "reason": "flatten"}
    return job, board.call(role, "POST", f"/api/jobs/{job}/{verb}", body)


LEGAL = [c for c in CASES if c[3] == 200]
ILLEGAL = [c for c in CASES if c[3] == 409]
ROLE_REFUSED = [c for c in CASES if c[3] == 403]


@pytest.mark.parametrize("case", LEGAL, ids=[_case_id(c) for c in LEGAL])
def test_legal_transition(shared_board, case):
    state, verb, role, _, target = case
    job, res = _run(shared_board, state, verb, role)
    assert res.status_code == 200, res.text
    assert shared_board.status(job) == target


@pytest.mark.parametrize("case", ILLEGAL, ids=[_case_id(c) for c in ILLEGAL])
def test_illegal_transition_is_409(shared_board, case):
    state, verb, role, _, _ = case
    job, res = _run(shared_board, state, verb, role)
    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert f"the job is {state}" in detail and "legal verbs:" in detail
    assert shared_board.status(job) == state


@pytest.mark.parametrize("case", ROLE_REFUSED, ids=[_case_id(c) for c in ROLE_REFUSED])
def test_role_refusal_is_403(shared_board, case):
    state, verb, role, _, _ = case
    job, res = _run(shared_board, state, verb, role)
    assert res.status_code == 403, res.text
    if role != "viewer":
        roles = transitions.roles_for(verb, Policy())
        assert ", ".join(roles) in res.json()["detail"]
    assert shared_board.status(job) == state


@pytest.mark.parametrize("role,code", [("owner", 200), ("orchestrator", 200), ("worker", 200),
                                       ("verifier", 403), ("viewer", 403)])
def test_add_roles(shared_board, role, code):
    assert shared_board.add(role).status_code == code


def test_no_verb_reaches_verified_except_a_verdict():
    for rule in transitions.TABLE:
        if rule.target == "verified":
            pytest.fail(f"{rule.verb} writes verified")
    assert transitions.verdict_target("completed_unverified", "PASS", 0, 3) == ("verified", 0)


def test_verdict_fail_requeues_then_blocks_at_max_rounds(board):
    job = board.insert_job("completed_unverified", closed_by="orchestrator")
    for expected_state in ("queued", "queued", "blocked"):
        res = board.call("verifier", "POST", f"/api/jobs/{job}/verdict",
                         {"verdict": "FAIL", "findings": ["greet.py missing"]})
        assert res.status_code == 200, res.text
        assert board.status(job) == expected_state
        if expected_state == "queued":
            with db.transaction(board.cfg.db_path) as c:
                c.execute("UPDATE jobs SET status='completed_unverified', closed_by='orchestrator' "
                          "WHERE id=?", (job,))
    trail = board.call("viewer", "GET", f"/api/jobs/{job}/trail").json()["trail"]
    assert [t["kind"] for t in trail].count("finding") == 3


def test_verdict_blocked_leaves_state_and_needs_a_reason(board):
    job = board.insert_job("completed_unverified", closed_by="orchestrator")
    assert board.call("verifier", "POST", f"/api/jobs/{job}/verdict",
                      {"verdict": "BLOCKED"}).status_code == 422
    res = board.call("verifier", "POST", f"/api/jobs/{job}/verdict",
                     {"verdict": "BLOCKED", "reason": "nothing verifiable"})
    assert res.status_code == 200 and board.status(job) == "completed_unverified"


def test_a_project_root_never_changes_state(board):
    for verb, who in (("claim", "worker"), ("cancel", "owner"), ("move", "owner")):
        body = {"reason": "x", "parent": str(board.root)}
        res = board.call(who, "POST", f"/api/jobs/{board.root}/{verb}", body)
        assert res.status_code == 409 and "project root" in res.json()["detail"]


def test_claim_waits_for_after_job(board):
    first = board.insert_job("queued")
    second = board.insert_job("queued", after_id=first)
    res = board.call("worker", "POST", f"/api/jobs/{second}/claim")
    assert res.status_code == 409 and f"after job {first}" in res.json()["detail"]
    with db.transaction(board.cfg.db_path) as c:
        c.execute("UPDATE jobs SET status='verified' WHERE id=?", (first,))
    assert board.call("worker", "POST", f"/api/jobs/{second}/claim").status_code == 200


@pytest.mark.parametrize("verb,state", [("block", "claimed"), ("reopen", "blocked"),
                                        ("cancel", "queued")])
def test_reason_is_required(board, verb, state):
    job = board.insert_job(state, assignee="owner")
    res = board.call("owner" if verb != "block" else "worker", "POST",
                     f"/api/jobs/{job}/{verb}", {"reason": "  "})
    assert res.status_code == 422 and "reason" in res.json()["detail"]
    assert board.status(job) == state


def test_only_requester_assignee_or_owner_closes(board):
    job = board.insert_job("claimed", requested_by="orchestrator", assignee="orchestrator")
    res = board.call("worker", "POST", f"/api/jobs/{job}/close", GOOD_EVIDENCE)
    assert res.status_code == 403 and "only the requester" in res.json()["detail"]
    assert board.call("owner", "POST", f"/api/jobs/{job}/close", GOOD_EVIDENCE).status_code == 200


def test_review_only_for_review_types_and_only_on_ship(board):
    code_job = board.insert_job("claimed", type="code")
    res = board.call("owner", "POST", f"/api/jobs/{code_job}/review", BODIES["review"])
    assert res.status_code == 409 and "close by review" in res.json()["detail"]
    doc_job = board.insert_job("claimed", type="docs")
    for verdict, needle in (("no verdict line", "no '# VERDICT"), ("# VERDICT: FIX", "FIX")):
        res = board.call("owner", "POST", f"/api/jobs/{doc_job}/review",
                         {"verdict": verdict, "done": "x"})
        assert res.status_code == 422 and needle in res.json()["detail"]
    res = board.call("owner", "POST", f"/api/jobs/{doc_job}/review",
                     {"verdict": "# VERDICT: SHIP", "done": " "})
    assert res.status_code == 422 and "DONE.md" in res.json()["detail"]
    assert board.status(doc_job) == "claimed"
