"""Goals and the goal-job guards on the board (docs/LEVEL5.md 4.0-4.2, wave L5-3); TestClient
against a migrated DB. Each refusal has a _red test beside its _green one.

  B2  max_attempts = 0 refused, a file with only max_attempts accepted (owner decision Q5)
  B6  the requester never approves its own DoD (kept from L5-2; here on a goal job)
  B10 a goal job carries goal_id and its budget, computed by the board
plus: goal_roles (a chat goal from the orchestrator only when configured), the chat proposal
(filed only by `confirm` from the same session), the filing window (the planner files and the
DoD reviewer reviews goal jobs only while the factory holds intake at `filing`), the factory's
approval after a dod-review SHIP, and the identity pairs planner / dod-reviewer / scenario /
factory / worker."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from konstant import config
from konstant.board import db
from konstant.board.app import create_app
from tests.board.conftest import Board

GOAL = '[goal]\nid = "greeter"\nproject = "demo"\ntext = "greet by name"\n[limits]\nmax_attempts = 3\n'
BRIEF = "greet\n\nDoD:\n- greeter.py exists\nPROBE: test -f {workdir}/greeter.py => ^ok$\n"


def reload(b: Board, toml: str) -> Board:
    (b.home / "konstant.toml").write_text(toml)
    b.cfg = config.load(b.home)
    b.client = TestClient(create_app(b.cfg))
    return b


@pytest.fixture()
def board(tmp_path):
    return Board(tmp_path)


@pytest.fixture()
def chat_board(tmp_path):
    return reload(Board(tmp_path), '[factory]\ngoal_roles = ["owner", "orchestrator"]\n')


def add_goal(b, who="owner", spec=GOAL, source="file", session=""):
    return b.call(who, "POST", "/api/goals", {"spec": spec, "source": source, "session": session})


def filing(b, slug="greeter"):
    for state in ("planning", "filing"):
        res = b.call("factory", "POST", f"/api/goals/{slug}/intake", {"state": state})
        assert res.status_code == 200, res.text


def goal_job(b, who="planner", **extra):
    body = {"title": "B1: greet", "project": "demo", "type": "code", "brief": BRIEF,
            "goal": "greeter", **extra}
    return b.call(who, "POST", "/api/jobs", body)


def ready(b) -> int:
    """A goal job filed by the planner inside the filing window (waiting_approval)."""
    assert add_goal(b).status_code == 200
    filing(b)
    res = goal_job(b)
    assert res.status_code == 200, res.text
    return res.json()["id"]


# --- goal files ----------------------------------------------------------------------------------

def test_B1_owner_adds_a_goal_and_the_board_copies_it(board):
    res = add_goal(board)
    assert res.status_code == 200, res.text
    g = res.json()
    assert g["status"] == "active" and g["source"] == "file" and g["intake"] == "none"
    copy = board.home / "var" / "factory" / "goals" / "greeter.toml"
    assert copy.read_text() == GOAL and oct(copy.stat().st_mode)[-3:] == "400"
    import hashlib
    assert g["spec_sha256"] == hashlib.sha256(GOAL.encode()).hexdigest()
    assert g["limits"]["max_attempts"] == 3 and g["spec"]["ship"]["target"] == "branch"


def test_B2_max_attempts_zero_red_and_only_max_attempts_green(board):
    bad = add_goal(board, spec=GOAL.replace("max_attempts = 3", "max_attempts = 0"))
    assert bad.status_code == 422 and "goal: limits.max_attempts must be >= 1" in bad.text
    assert add_goal(board).status_code == 200                # no wall_clock/tokens/cost: fine
    lim = board.call("viewer", "GET", "/api/goals/greeter").json()["limits"]
    assert lim["wall_clock"] == "0" and lim["max_tokens"] == 0 and lim["max_cost_usd"] == 0


@pytest.mark.parametrize("spec,needle", [
    (GOAL + "[ship]\ntarget = \"ftp\"\n", "ship.target"),
    (GOAL + "[holdout]\nauthor = \"robot\"\n", "holdout.author"),
    (GOAL + "[budget]\nx = 1\n", "unknown table [budget]"),
    (GOAL.replace('id = "greeter"', 'id = "Greeter Goal"'), "goal.id must be a slug"),
    (GOAL.replace('project = "demo"', 'project = "nope"'), "not a konstant project"),
    (GOAL.replace("max_attempts = 3", 'max_attempts = 3\nwall_clock = "soon"'), "wall_clock"),
])
def test_a_malformed_goal_is_refused_red(board, spec, needle):
    res = add_goal(board, spec=spec)
    assert res.status_code == 422 and needle in res.text, res.text


def test_goal_id_is_used_once_and_the_spec_is_immutable(board):
    assert add_goal(board).status_code == 200
    assert add_goal(board).status_code == 409
    with pytest.raises(Exception, match="immutable"):
        with db.transaction(board.cfg.db_path) as conn:
            conn.execute("UPDATE goals SET spec_text='x' WHERE slug='greeter'")


def test_goal_add_from_a_file_needs_the_owner_red(board):
    res = add_goal(board, who="orchestrator")
    assert res.status_code == 403 and "requires role owner" in res.text
    assert add_goal(board, who="factory").status_code == 403       # never an identity


# --- the chat (4.0) -----------------------------------------------------------------------------

def test_chat_goal_needs_goal_roles_red_public_default(board):
    res = add_goal(board, who="orchestrator", source="chat", session="s1")
    assert res.status_code == 403 and "goal_roles" in res.text


def test_chat_goal_is_proposed_then_confirmed_by_its_own_session_green(chat_board):
    b = chat_board
    res = add_goal(b, who="orchestrator", source="chat", session="s1")
    assert res.status_code == 200 and res.json()["status"] == "proposed", res.text
    copy = b.home / "var" / "factory" / "goals" / "greeter.toml"
    assert not copy.exists()                                 # nothing filed before the yes
    other = b.call("orchestrator", "POST", "/api/goals/greeter/confirm", {"session": "s2"})
    assert other.status_code == 403                          # another session never confirms
    ok = b.call("orchestrator", "POST", "/api/goals/greeter/confirm", {"session": "s1"})
    assert ok.status_code == 200 and ok.json()["status"] == "active" and ok.json()["source"] == "chat"
    assert copy.read_text() == GOAL


def test_a_withdrawn_proposal_frees_its_id(chat_board):
    b = chat_board
    assert add_goal(b, who="orchestrator", source="chat", session="s1").status_code == 200
    w = b.call("orchestrator", "POST", "/api/goals/greeter/withdraw", {"session": "s1"})
    assert w.status_code == 200 and w.json()["status"] == "withdrawn"
    assert b.call("orchestrator", "POST", "/api/goals/greeter/confirm",
                  {"session": "s1"}).status_code == 409
    assert add_goal(b).status_code == 200


def test_pause_resume_cancel_roles(board):
    assert add_goal(board).status_code == 200
    assert board.call("orchestrator", "POST", "/api/goals/greeter/pause").status_code == 403
    assert board.call("factory", "POST", "/api/goals/greeter/pause").json()["status"] == "paused"
    assert board.call("factory", "POST", "/api/goals/greeter/resume").status_code == 403
    assert board.call("owner", "POST", "/api/goals/greeter/resume").json()["status"] == "active"
    assert board.call("owner", "POST", "/api/goals/greeter/cancel").json()["status"] == "stopped"
    assert board.call("owner", "POST", "/api/goals/greeter/resume").status_code == 409


# --- the filing window (4.2 step 3) ---------------------------------------------------------------

def test_planner_files_a_goal_job_only_inside_the_filing_window_red(board):
    assert add_goal(board).status_code == 200
    res = goal_job(board)
    assert res.status_code == 409 and "only while the factory files" in res.text


def test_goal_job_filed_by_the_planner_in_the_window_green_B10(board):
    jid = ready(board)
    j = board.call("viewer", "GET", f"/api/jobs/{jid}").json()
    assert j["status"] == "waiting_approval" and j["holdout_required"] is True
    assert j["goal_id"] and j["goal"] == "greeter" and j["requested_by"] == "planner"
    assert j["budget"] == {"max_attempts": 3, "goal_limits": {}} and j["ship_mode"] == "auto"


def test_only_the_planner_files_goal_jobs_and_only_under_the_goals_project_red(board):
    assert add_goal(board).status_code == 200
    filing(board)
    for who in ("worker", "orchestrator", "owner", "dod-reviewer"):
        assert goal_job(board, who).status_code == 403, who
    board.call("owner", "POST", "/api/projects", {"slug": "other"})
    res = goal_job(board, project="other")
    assert res.status_code == 409 and "its own project" in res.text


def test_infra_goal_job_ships_by_decision_and_max_jobs_holds(board):
    spec = GOAL.replace("max_attempts = 3", "max_attempts = 3\nmax_jobs = 1")
    assert add_goal(board, spec=spec).status_code == 200
    filing(board)
    first = goal_job(board, type="infra")
    assert first.status_code == 200 and first.json()["ship_mode"] == "decision"
    assert first.json()["budget"]["goal_limits"] == {"max_jobs": 1}
    res = goal_job(board)
    assert res.status_code == 409 and "max_jobs = 1" in res.text


def test_intake_state_is_the_factory_identitys_and_filed_is_final(board):
    assert add_goal(board).status_code == 200
    assert board.call("owner", "POST", "/api/goals/greeter/intake",
                      {"state": "planning"}).status_code == 403
    filing(board)
    assert board.call("factory", "POST", "/api/goals/greeter/intake",
                      {"state": "filed"}).status_code == 200
    res = board.call("factory", "POST", "/api/goals/greeter/intake", {"state": "planning"})
    assert res.status_code == 409 and "taken in once" in res.text


def test_intake_type_is_never_a_job(board):
    res = board.add(type="intake")
    assert res.status_code == 422 and "never as a job" in res.text


# --- review + approval (4.2 steps 2, 4) ----------------------------------------------------------

def review(b, jid, word="SHIP", who="dod-reviewer"):
    return b.call(who, "POST", f"/api/jobs/{jid}/dod-review", {"verdict": word, "reason": "ok"})


def test_dod_review_of_a_goal_job_only_inside_the_window_red(board):
    jid = ready(board)
    board.call("factory", "POST", "/api/goals/greeter/intake", {"state": "filed"})
    res = review(board, jid)
    assert res.status_code == 409 and "never from a phase" in res.text


def test_factory_approves_only_after_a_dod_review_ship_red_then_green(board):
    jid = ready(board)
    res = board.call("factory", "POST", f"/api/jobs/{jid}/approve")
    assert res.status_code == 409 and "no dod-review SHIP" in res.text          # red
    assert review(board, jid, "FIX").status_code == 200
    assert board.call("factory", "POST", f"/api/jobs/{jid}/approve").status_code == 409
    assert review(board, jid).status_code == 200
    ok = board.call("factory", "POST", f"/api/jobs/{jid}/approve")
    assert ok.status_code == 200 and ok.json()["status"] == "queued"            # green
    trail = board.call("viewer", "GET", f"/api/jobs/{jid}/trail").json()["trail"]
    assert [t["actor"] for t in trail] == ["planner", "dod-reviewer", "dod-reviewer", "factory"]


def test_owner_also_needs_the_dod_review_on_a_goal_job_red(board):
    jid = ready(board)
    assert board.call("owner", "POST", f"/api/jobs/{jid}/approve").status_code == 409


def test_factory_never_approves_a_level4_job_red(board):
    res = board.add("orchestrator", approval=True)
    res = board.call("factory", "POST", f"/api/jobs/{res.json()['id']}/approve")
    assert res.status_code == 403 and "goal jobs only" in res.text


def test_B6_requester_approving_its_own_goal_job_red(board):
    jid = ready(board)
    assert review(board, jid).status_code == 200
    tok = board.add_token("owner", "planner")
    res = board.call(tok, "POST", f"/api/jobs/{jid}/approve")
    assert res.status_code == 403 and "the requester cannot approve its own DoD" in res.text


# --- identity pairs: who never claims (2.2) ------------------------------------------------------

def approved(b) -> int:
    jid = ready(b)
    assert review(b, jid).status_code == 200
    assert b.call("factory", "POST", f"/api/jobs/{jid}/approve").status_code == 200
    with db.transaction(b.cfg.db_path) as conn:       # level-4 claim path for the pair checks
        conn.execute("UPDATE jobs SET holdout_required=0 WHERE id=?", (jid,))
    return jid


@pytest.mark.parametrize("who,needle", [
    ("planner", "the planner of a job cannot claim it"),
    ("dod-reviewer", "the DoD reviewer of a job cannot claim it"),
    ("factory", "the factory identity cannot claim a job"),
    ("scenario", "the scenario identity cannot claim a job"),
])
def test_factory_identities_never_claim_a_goal_job_red(board, who, needle):
    jid = approved(board)
    res = board.call(who, "POST", f"/api/jobs/{jid}/claim")
    assert res.status_code == 403 and needle in res.text, res.text


def test_worker_claims_the_goal_job_green(board):
    jid = approved(board)
    assert board.call("worker", "POST", f"/api/jobs/{jid}/claim").status_code == 200


def test_red_twin_without_the_identity_guard_the_planner_claims(board, monkeypatch):
    from konstant.board.api import lifecycle
    jid = approved(board)
    monkeypatch.setattr(lifecycle, "identity_guard", lambda *a, **k: None)
    assert board.call("planner", "POST", f"/api/jobs/{jid}/claim").status_code == 200


def test_goal_list_and_show(board):
    jid = ready(board)
    rows = board.call("viewer", "GET", "/api/goals").json()["goals"]
    assert [g["slug"] for g in rows] == ["greeter"]
    g = board.call("viewer", "GET", "/api/goals/greeter").json()
    assert [j["id"] for j in g["jobs"]] == [jid] and g["jobs_by_state"] == {"waiting_approval": 1}
    assert "spec_text" not in g and json.dumps(g)
