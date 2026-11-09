"""The loop after a rollback and a worn holdout set (docs/LEVEL5.md 6.1 steps 6-7, 5.3 step 4,
3.6 step 6; wave L5-5): the factory files nothing itself, it drives what the board and the ship
step decided.

  follow-up  a post-ship failure rolls the ship back; the board's follow-up job runs through the
             whole loop and ships; the job `after` the rolled-back one waits for the follow-up
             (it never builds on code a rollback took out); the goal ends done, nothing notified
  still broken  a follow-up whose producer breaks the same thing again fails its own DoD (the
             failed post-ship probe is a PROBE row of it) and is BLOCKED at max_rounds before any
             second ship: one notification, the dependent job stays put, exit 4 (max_rollbacks
             itself: tests/ship/test_ship_goal.py)
  worn set   a producer that overfits fails its holdouts; after [holdout] max_failed_rounds the
             set is worn, the factory has the scenario writer seal a fresh set, and the board
             blocks the job at max_rounds: one BLOCKED notification, no ship, exit 4
"""
from __future__ import annotations

from tests.factory.loopkit import events, factory, jobs, make_lws, notify_lines
from tests.holdout.conftest import needs_jail


@needs_jail
def test_rolled_back_job_follow_up_ships_and_the_goal_ends_done_green(tmp_path):
    s = make_lws(tmp_path)
    try:
        r = factory(s, "run", "greeter", "--until-idle", mode="ship-break",
                    FAKE_HARNESS_BREAK_JOBS="2")
        assert r.returncode == 0, r.stderr[-4000:]
        ships = s.ships()
        assert [(x["job_id"], x["state"]) for x in ships] == [(2, "rolled_back"),
                                                               (4, "shipped"), (3, "shipped")]
        assert ships[0]["follow_up_id"] == 4
        assert notify_lines(s) == []
        assert [e["event"] for e in events(s) if e["event"] == "ROLLED_BACK"] == ["ROLLED_BACK"]
        assert s.w.json("goal", "show", "greeter")["status"] == "done"
    finally:
        s.w.stop_board()


@needs_jail
def test_follow_up_that_still_breaks_is_caught_by_its_own_dod_red(tmp_path):
    """Every producer breaks the shipped state: the first job ships and is rolled back; its
    follow-up carries the failed post-ship probe as a PROBE row of its DoD, so the VERIFIER fails
    it before any ship, and it is blocked (max_rounds or max_attempts): one BLOCKED, no second
    ship."""
    s = make_lws(tmp_path, limits="max_rollbacks = 1")
    try:
        r = factory(s, "run", "greeter", "--until-idle", mode="ship-break")
        assert r.returncode == 4, r.stderr[-4000:]
        ships = s.ships()
        assert [(x["job_id"], x["state"]) for x in ships] == [(2, "rolled_back")]
        fu = s.w.json("job", "show", ships[0]["follow_up_id"])
        assert "PROBE: test -f {workdir}/README.md" in fu["acceptance"]
        # blocked by the board at max_rounds (three FAIL verdicts) or, when an attempt's own DoD
        # check already read the last FAIL from the board (the level-4 `verified` rule, second
        # precision) and ended UNMET, by its third attempt (max_attempts): both stop it unshipped
        verdicts = [v["verdict"] for v in fu["verifications"]]
        assert fu["status"] == "blocked" and len(fu["runs"]) == 3, (fu["status"], fu["runs"])
        assert len(verdicts) >= 2 and set(verdicts) == {"FAIL"}, verdicts
        lines = notify_lines(s)
        assert len(lines) == 1 and lines[0].startswith(f"BLOCKED greeter job "
                                                       f"{fu['display_id']}"), lines
        assert [j["status"] for j in jobs(s)] == ["verified", "queued", "blocked"]
        assert s.w.json("goal", "show", "greeter")["status"] == "active"
    finally:
        s.w.stop_board()


@needs_jail
def test_worn_holdout_set_is_rotated_then_max_rounds_blocks_red(tmp_path):
    s = make_lws(tmp_path)
    try:
        r = factory(s, "run", "greeter", "--until-idle", mode="overfit")
        assert r.returncode == 4, r.stderr[-4000:]
        first = jobs(s)[0]
        j = s.w.json("job", "show", first["id"])
        gens = sorted({(h["generation"], h["state"]) for h in j["holdouts"]})
        assert gens == [(1, "retired"), (2, "sealed")], gens               # rotated once
        assert j["status"] == "blocked" and len(j["runs"]) == 3
        assert any(v["verdict"] == "FAIL" for v in j["verifications"])
        assert s.ships() == []                                             # never shipped
        lines = notify_lines(s)
        assert len(lines) == 1 and lines[0].startswith("BLOCKED greeter job 1.1"), lines
        steps = sorted((s.w.home / "var" / "factory" / "steps").glob("*-author-*"))
        assert len(steps) == 1                                   # the factory's rotation hook
    finally:
        s.w.stop_board()
