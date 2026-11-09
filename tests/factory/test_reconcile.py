"""An interrupted ship, reconciled when the factory resumes (docs/LEVEL5.md 6.1; the known gap of
L5-4: a ship killed between the board's `shipping` row and the end of its target move left the
row in flight, and the guard then refused every ship forever).

The interruption is made with konstant's own ship code, stopped where a kill would stop it: the
board's `shipping` row written (and, per case, the target moved, or also the `shipped` record),
then nothing more. Then `konstant ship` is refused (the old dead end: red), and `factory run`
reconciles by comparing the TARGET with the row:
  not moved      -> the row `failed`, the job ships again, the goal runs to done
  moved          -> the row `shipped`, post-ship checks run, the goal runs to done
  shipped, cut   -> (the shipped record written, no post-ship checks) the checks run, done
  moved elsewhere-> the row `failed`, ALL shipping halted, HALTED escalated (konstant does not
                   guess), exit 4
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from tests.factory.loopkit import factory, jobs, make_lws, notify_lines
from tests.holdout.conftest import needs_jail
from tests.ship.conftest import commit_in, git_out

CUT = """
import sys
from konstant import config
from konstant.client import Client, token_for
from konstant.factory import ship
cfg = config.load()
c = Client(cfg.base_url, token_for(cfg, "factory"))
plan = ship.prepare(cfg, c, int(sys.argv[1]))
made = ship.board_check(c, plan, dry=False)
sid = made["ship"]
if sys.argv[2] in ("moved", "post"):
    tip = plan["tgt"].ship(sid, plan["commit"])
    if sys.argv[2] == "post":
        c.post(f"/api/ships/{sid}", {"state": "shipped", "tip": tip})
print(sid)
"""


def verified_first_job(s) -> int:
    for _ in range(2):                         # tick 1: intake; tick 2: the first job's attempt
        r = factory(s, "run", "greeter", "--once")
        assert r.returncode == 0, r.stderr[-3000:]
    rows = jobs(s)
    assert rows[0]["status"] == "verified" and s.ships() == [], rows
    return rows[0]["id"]


def cut_ship(s, jid: int, how: str) -> int:
    r = subprocess.run([sys.executable, "-c", CUT, str(jid), how], capture_output=True,
                       text=True, env=s.w.env(), cwd=str(s.w.home), timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return int(r.stdout.strip())


@needs_jail
@pytest.mark.parametrize("how", ["not-moved", "moved", "post"])
def test_interrupted_ship_is_reconciled_on_resume_red_green(tmp_path, how):
    s = make_lws(tmp_path)
    try:
        jid = verified_first_job(s)
        pre = git_out(s.target, "rev-parse", "main")
        sid = cut_ship(s, jid, how)
        assert s.ships()[0]["state"] == ("shipped" if how == "post" else "shipping")
        moved = git_out(s.target, "rev-parse", "main")
        assert (moved == pre) == (how == "not-moved")
        r = s.ship(jid)                                    # red: the L5-4 dead end
        assert r.returncode == 1 and f"ship {sid} is in flight" in (r.stderr + r.stdout), r
        r = factory(s, "run", "greeter", "--until-idle")
        assert r.returncode == 0, r.stderr[-4000:]
        assert f"reconciled ship {sid}" in r.stderr
        ships = s.ships()
        if how == "not-moved":
            assert [x["state"] for x in ships] == ["failed", "shipped", "shipped"]
            assert "interrupted before the target moved" in ships[0]["reason"]
            assert ships[1]["job_id"] == jid
        else:
            assert [x["state"] for x in ships] == ["shipped", "shipped"]
            assert ships[0]["post"] is not None and ships[0]["post"]["ok"] is True
        assert notify_lines(s) == []
        rows = jobs(s)
        assert git_out(s.target, "rev-parse", "main") == s.commit(rows[1]["id"])
        assert s.w.json("goal", "show", "greeter")["status"] == "done"
    finally:
        s.w.stop_board()


@needs_jail
def test_interrupted_ship_with_a_target_moved_elsewhere_halts_shipping_red(tmp_path):
    s = make_lws(tmp_path)
    try:
        jid = verified_first_job(s)
        sid = cut_ship(s, jid, "not-moved")
        commit_in(s.target, "OUTSIDE.md", "a commit made outside the factory\n")
        r = factory(s, "run", "greeter", "--until-idle")
        assert r.returncode == 4, r.stderr[-3000:]
        ships = s.ships()
        assert ships[0]["state"] == "failed" and len(ships) == 1
        assert "neither its base nor the shipped commit" in ships[0]["reason"]
        assert s.w.json("factory", "status")["shipping"] == "halted"
        lines = notify_lines(s)
        assert len(lines) == 1 and lines[0].startswith("HALTED greeter job 1.1"), lines
        assert f"interrupted ship {sid}" in lines[0]
    finally:
        s.w.stop_board()
