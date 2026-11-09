"""Goal jobs through ship (docs/LEVEL5.md 5.2 rule 6, 5.3 step 4; wave L5-4): two jobs of one goal
filed the way intake files them (planner in the filing window, dod-review SHIP, factory approval),
holdouts sealed, run to `verified` by the fake harness. A rolled-back job gets a follow-up job
that runs through the whole loop and ships; the goal's max_rollbacks turns the next rollback into
BLOCKED; a paused goal does not ship."""
from __future__ import annotations

import json
import subprocess
import sys

from tests.holdout.conftest import BRIEF, H1, H2, needs_jail
from tests.ship.conftest import README_PROBE, git_out, make_ship_ws
from tests.ship.test_ship_units import board_post

GOAL = """[goal]
id = "greeter"
project = "greeter"
text = "greet by name"
[limits]
max_attempts = 3
max_rollbacks = 1
[ship]
post_probes = ["PROBE: grep -c greet {workdir}/greeter.py => ^[1-9]"]
"""


def run_job(s, jid, mode=""):
    env = s.w.henv()
    if mode:
        env["FAKE_HARNESS_MODE"] = mode
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet(name)", "--job", str(jid), "--harness", "dsh"],
                         capture_output=True, text=True, env=env, timeout=900,
                         cwd=str(s.w.home))
    assert res.returncode == 0, res.stderr[-2000:]
    assert s.job(jid)["status"] == "verified"


@needs_jail
def test_goal_jobs_roll_back_follow_up_ships_and_max_rollbacks_blocks(tmp_path):
    s = make_ship_ws(tmp_path, tail='[notify]\nkind = "file"\n')
    try:
        g = s.w.src / "goal.toml"
        g.write_text(GOAL)
        s.w.ok("--as", "owner", "goal", "add", g)
        for st in ("planning", "filing"):
            assert board_post(s, "/api/goals/greeter/intake", {"state": st}).get("intake") == st
        jobs = []
        for _ in range(2):
            j = board_post(s, "/api/jobs", {"title": "greet by name", "project": "greeter",
                                            "brief": BRIEF, "type": "code", "goal": "greeter"},
                           "planner")
            assert board_post(s, f"/api/jobs/{j['id']}/dod-review",
                              {"verdict": "SHIP", "reason": "probes settle it"},
                              "dod-reviewer").get("id") == j["id"]
            jobs.append(j["id"])
        board_post(s, "/api/goals/greeter/intake", {"state": "filed"})
        for jid in jobs:
            assert board_post(s, f"/api/jobs/{jid}/approve", {}).get("status") == "queued"
            assert s.w.seal(jid, H1, H2).returncode == 0
        a, b = jobs
        run_job(s, a, "ship-break")
        r = s.ship(a, "--json")
        assert r.returncode == 3, r.stderr + r.stdout[-1500:]
        fu = s.job(s.ships()[0]["follow_up_id"])
        assert fu["goal"] == "greeter" and fu["status"] == "queued" and \
            README_PROBE in fu["acceptance"]
        # the second rollback of the goal passes max_rollbacks = 1: BLOCKED, no follow-up
        run_job(s, b, "ship-break")
        r = s.ship(b, "--json")
        assert r.returncode == 3 and json.loads(r.stdout)["follow_up"] is None
        assert s.ships()[1]["follow_up_id"] is None
        log = (s.w.home / "var" / "factory" / "notify.log").read_text().splitlines()
        assert any(x.startswith("BLOCKED greeter") and "max_rollbacks = 1" in x for x in log)
        # the follow-up runs through the whole loop: its holdouts are the original commitments
        run_job(s, fu["id"])
        s.w.ok("--as", "owner", "goal", "pause", "greeter")
        r = s.ship(fu["id"])
        assert r.returncode == 1 and "goal greeter is paused" in r.stderr, r.stderr
        s.w.ok("--as", "owner", "goal", "resume", "greeter")
        r = s.ship(fu["id"], "--json")
        assert r.returncode == 0, r.stderr + r.stdout[-1500:]
        post = s.ships()[2]["post"]["checks"]
        assert any("grep -c greet" in c["reason"] and c["ok"] for c in post)   # the goal's probe
        assert git_out(s.target, "rev-parse", "main") == s.commit(fu["id"])
    finally:
        s.w.stop_board()
