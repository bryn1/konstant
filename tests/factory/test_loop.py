"""The factory loop end to end (docs/LEVEL5.md 6.6, wave L5-5): goals taken in, jobs attempted,
verified, shipped, budgets kept, escalations told once, all offline (stub dsh + fake harness).

  D3  an honest goal run to completion: exit 0, notify.log empty, SHIPPED rows in events.jsonl,
      every job verified and shipped, the target's main at the last shipped commit
  D8  the same with owner.token unreadable: the loop never needs a human role
  D1  max_task_runs = 1 (an optional limit) + tester-fails-3x: exit 4, ONE `BUDGET_STOP greeter`
      line, the goal paused
  D1b only max_attempts = 3 (Q5) + tester-fails-3x: the job BLOCKED after its 3rd attempt, ONE
      BLOCKED notification, no BUDGET_STOP, exit 4
  D2  max_cost_usd on the command harness: exit 2 before the start
Each refusal has a _red (the guard fires) and a _green (its allowed twin) test."""
from __future__ import annotations

import json
import os

from tests.factory.loopkit import events, factory, goal, jobs, make_lws, notify_lines
from tests.holdout.conftest import needs_jail
from tests.ship.conftest import git_out


@needs_jail
def test_D3_D8_D1b_honest_goal_runs_to_done_without_a_human_role_green(tmp_path):
    s = make_lws(tmp_path)
    try:
        os.chmod(s.w.home / "var" / "secrets" / "owner.token", 0)        # D8
        r = factory(s, "run", "greeter", "--until-idle", "--json")
        assert r.returncode == 0, r.stderr[-4000:]
        assert notify_lines(s) == []
        shipped = [e for e in events(s) if e["event"] == "SHIPPED"]
        assert len(shipped) == 2, [e["event"] for e in events(s)]
        assert any(e["event"] == "GOAL_DONE" for e in events(s))
        os.chmod(s.w.home / "var" / "secrets" / "owner.token", 0o600)
        rows = jobs(s)
        assert [r["status"] for r in rows] == ["verified", "verified"]
        ships = s.ships()
        assert [x["state"] for x in ships] == ["shipped", "shipped"]
        assert git_out(s.target, "rev-parse", "main") == s.commit(rows[1]["id"])
        assert goal(s)["status"] == "done"
    finally:
        os.chmod(s.w.home / "var" / "secrets" / "owner.token", 0o600)
        s.w.stop_board()


def budget_events(s) -> list:
    return [e["event"] for e in events(s) if e["kind"] == "escalation"
            and not e.get("suppressed")]


@needs_jail
def test_D1_optional_task_run_limit_stops_the_goal_red(tmp_path):
    s = make_lws(tmp_path, limits="max_task_runs = 1")
    try:
        r = factory(s, "run", "greeter", "--until-idle", mode="tester-fails-3x")
        assert r.returncode == 4, r.stderr[-3000:]
        lines = notify_lines(s)
        assert len(lines) == 1 and lines[0].startswith("BUDGET_STOP greeter"), lines
        assert "max_task_runs 1 reached (1 used)" in lines[0]
        assert goal(s)["status"] == "paused"
        view = s.w.json("factory", "status")
        assert view["open_escalations"] == 1
    finally:
        s.w.stop_board()


@needs_jail
def test_D1b_max_attempts_blocks_the_job_after_its_third_attempt_red(tmp_path):
    s = make_lws(tmp_path)
    try:
        r = factory(s, "run", "greeter", "--until-idle", mode="tester-fails-3x")
        assert r.returncode == 4, r.stderr[-3000:]
        lines = notify_lines(s)
        assert len(lines) == 1 and lines[0].startswith("BLOCKED greeter job 1.1"), lines
        assert "3 of 3 attempts used" in lines[0]
        assert not any(x.startswith("BUDGET_STOP") for x in lines)
        rows = jobs(s)
        assert rows[0]["status"] == "blocked" and rows[1]["status"] == "queued"
        j = s.w.json("job", "show", rows[0]["id"])
        assert len(j["runs"]) == 3                                  # exactly three attempts
        g = s.w.json("factory", "status")
        assert goal(s)["status"] == "active" and g["open_escalations"] == 1
        # one notification per (goal, job, event): a second run tells nothing new
        r = factory(s, "run", "greeter", "--until-idle", mode="tester-fails-3x")
        assert r.returncode == 4 and len(notify_lines(s)) == 1, notify_lines(s)
        assert len(s.w.json("job", "show", rows[0]["id"])["runs"]) == 3
    finally:
        s.w.stop_board()


def test_D2_cost_budget_on_a_harness_that_cannot_measure_it_red(tmp_path):
    from tests.factory.conftest import FAKE
    s = make_lws(tmp_path, limits="max_cost_usd = 5",
                 harness=f'[harness]\nname = "command"\ncommand = "{FAKE}"\n')
    try:
        r = factory(s, "run", "greeter", "--until-idle")
        assert r.returncode == 2, r.stderr
        assert "budget max_cost_usd cannot be measured on harness command" in r.stderr
        assert jobs(s) == [] and events(s) == []                    # nothing started
    finally:
        s.w.stop_board()


def test_D2_cost_budget_on_a_measuring_harness_green(tmp_path):
    """The allowed twin: claude with --output-format json reports usage, so the same limit is
    accepted (the dry run plans the intake instead of refusing)."""
    from tests.fixtures import stub_cli
    cmd = 'claude -p --output-format json --permission-mode dontAsk {prompt}'
    s = make_lws(tmp_path, limits="max_cost_usd = 5",
                 harness=f'[harness]\nname = "claude"\ncommand = "{cmd}"\n')
    try:
        stub_cli.install(s.w.bindir, "claude")
        from konstant import harnesses
        assert harnesses.adapter("claude").measures({"command": cmd})
        assert not harnesses.adapter("command").measures({"command": cmd})
        r = factory(s, "run", "greeter", "--dry-run", "--json")
        assert r.returncode == 0, r.stderr
        assert [a["action"] for a in json.loads(r.stdout)["actions"]] == ["intake"]
    finally:
        s.w.stop_board()


@needs_jail
def test_D1_a_limit_reached_exactly_by_finished_work_does_not_stop_the_goal_green(tmp_path):
    """The allowed twin of D1: max_task_runs = 2 and two honest jobs: the limit is reached by the
    second attempt, but nothing is left to start, so no BUDGET_STOP; the goal is done."""
    s = make_lws(tmp_path, limits="max_task_runs = 2")
    try:
        r = factory(s, "run", "greeter", "--until-idle")
        assert r.returncode == 0, r.stderr[-3000:]
        assert notify_lines(s) == [] and goal(s)["status"] == "done"
        view = s.w.json("factory", "status")
        assert view["goals"][0]["status"] == "done"
    finally:
        s.w.stop_board()
