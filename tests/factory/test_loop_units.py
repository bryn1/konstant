"""Unit tests of the factory loop's decisions (factory/steps.py), budgets (factory/budget.py), the
process files (factory/proc.py), the unit file (factory/unit.py) and the adapters' usage hook:
pure code over synthetic board records, each decision red beside its allowed green twin."""
from __future__ import annotations

import json
import time
from pathlib import Path

from konstant.factory import budget, proc, steps, unit


def goal(**kw) -> dict:
    g = {"id": 1, "slug": "g", "status": "active", "intake": "filed",
         "spec": {"holdout": {"author": "agent", "min_per_job": 2},
                  "limits": {"max_attempts": 3}}, "view": {"jobs": []}}
    g.update(kw)
    return g


def job(jid=2, status="queued", **kw) -> dict:
    j = {"id": jid, "display_id": f"1.{jid - 1}", "goal_id": 1, "project": "p", "status": status,
         "type": "code", "title": "t", "holdout_required": True, "workdir": None,
         "after_id": None, "holdouts": [{"state": "sealed"}, {"state": "sealed"}], "runs": [],
         "verifications": [], "trail": [], "evidence": None}
    j.update(kw)
    return j


def plan(g, jobs, ships=(), esc=(), halted=False, running=(), locked=lambda j: False,
         attempts=None):
    g["view"] = {"jobs": [{"id": j["id"], "attempts": (attempts or {}).get(j["id"], 0),
                           "max_attempts": 3} for j in jobs]}
    p = steps.Planner([g], {j["id"]: j for j in jobs}, list(ships), list(esc), halted,
                      set(running), {j["id"]: 2 for j in jobs}, locked)
    return p, p.goal_actions(g)


def kinds(acts) -> list:
    return [(a.kind, a.job, a.event or None) for a in acts]


def test_intake_none_and_cut_off_planning_take_the_goal_in():
    for state in ("none", "planning"):
        _p, acts = plan(goal(intake=state), [])
        assert kinds(acts) == [("intake", None, None)]
    _p, acts = plan(goal(intake="planning"), [], running=[("intake", "g", None)])
    assert acts == []                                           # green: one intake at a time


def test_intake_cut_off_while_filing_escalates_once_red_green():
    _p, acts = plan(goal(intake="filing"), [])
    assert kinds(acts) == [("escalate", None, "BLOCKED")]                       # red
    esc = [{"open": True, "goal": "g", "job_id": None, "kind": "BLOCKED"}]
    p, acts = plan(goal(intake="filing"), [], esc=esc)
    assert acts == [] and p.state["g"] == "stuck"                               # told once


def test_attempt_after_and_serial_project():
    a, b = job(2), job(3, after_id=2)
    _p, acts = plan(goal(), [a, b])
    assert kinds(acts) == [("attempt", 2, None)]              # b waits for a's shipped work
    a2 = job(2, status="verified", workdir="projects/p@2")
    _p, acts = plan(goal(), [a2, b], ships=[{"job_id": 2, "state": "shipped", "post": {"ok": 1},
                                              "follow_up_id": None}])
    assert kinds(acts) == [("attempt", 3, None)]
    c = job(4, workdir=None)
    busy = job(2, status="claimed", workdir="projects/p@2")
    _p, acts = plan(goal(), [busy, c], running=[("attempt", "g", 2)])
    assert acts == []                                   # one job of a project at a time


def test_after_a_rollback_the_dependent_waits_for_the_follow_up():
    a = job(2, status="verified", workdir="w")
    fu, b = job(4), job(3, after_id=2)
    ships = [{"job_id": 2, "state": "rolled_back", "post": {}, "follow_up_id": 4}]
    _p, acts = plan(goal(), [a, b, fu], ships=ships)
    assert kinds(acts) == [("attempt", 4, None)]


def test_exhausted_attempts_block_red_green():
    j = job(2, status="claimed", workdir="w", runs=[{"result": "UNMET", "run_dir": "/x/r"}])
    _p, acts = plan(goal(), [j], attempts={2: 3})
    assert kinds(acts) == [("exhaust", 2, None)]                                 # red
    _p, acts = plan(goal(), [j], attempts={2: 2})
    assert kinds(acts) == [("attempt", 2, None)]                                 # green


def test_a_locked_clone_is_waited_for_never_attempted():
    j = job(2, status="claimed", workdir="w")
    p, acts = plan(goal(), [j], locked=lambda x: True)
    assert acts == [] and p.state["g"] == "stuck"


def test_blocked_dod_check_retries_but_a_dispute_is_a_decision(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (tmp_path / "record.json").write_text(json.dumps({"out": str(out)}))
    j = job(2, status="claimed", workdir="w", runs=[{"result": "BLOCKED",
                                                       "run_dir": str(tmp_path)}])
    _p, acts = plan(goal(), [j])
    assert kinds(acts) == [("attempt", 2, None)]              # green: a failed attempt
    (out / "DONE.md").write_text("ID | claim | STATUS | evidence\nDISPUTE | H1 | the holdout "
                                 "contradicts the DoD row two\n")
    _p, acts = plan(goal(), [j])
    assert kinds(acts) == [("escalate", 2, "DECISION")]                          # red
    assert "holdout DISPUTE H1" in acts[0].reason


def test_verify_blocked_leak_and_blocked_escalate():
    close = {"kind": "evidence", "body": "closed by orchestrator", "ts": "2026-01-01T00:00:00Z"}
    for leak, ev in ((True, "LEAK"), (False, "BLOCKED")):
        j = job(2, status="completed_unverified", workdir="w", trail=[close],
                verifications=[{"verdict": "BLOCKED", "finished_at": "2026-01-01T00:00:01Z",
                                "holdouts": {"leak": leak, "reasons": ["LEAK: canary"]}}])
        _p, acts = plan(goal(), [j])
        assert kinds(acts) == [("escalate", 2, ev)]
    j = job(2, status="completed_unverified", workdir="w", trail=[close])
    _p, acts = plan(goal(), [j])
    assert kinds(acts) == [("verify", 2, None)]        # closed, no verdict: the verifier runs


def test_ship_rules_halt_decision_and_approval():
    j = job(2, status="verified", workdir="w", evidence={"commit": "c" * 40})
    _p, acts = plan(goal(), [j])
    assert kinds(acts) == [("ship", 2, None)]                                    # green
    _p, acts = plan(goal(), [j], halted=True)
    assert acts == []                                                            # red: halt
    esc = [{"open": True, "goal": "g", "job_id": 2, "kind": "DECISION"}]
    _p, acts = plan(goal(), [j], esc=esc)
    assert acts == []                                               # red: owner decides
    j["trail"] = [{"kind": "approval", "role": "owner", "payload": {"ship_decision": "c" * 40}}]
    _p, acts = plan(goal(), [j], esc=esc)
    assert kinds(acts) == [("ship", 2, None)]                     # green: owner approved
    _p, acts = plan(goal(), [j], ships=[{"job_id": 2, "state": "shipping", "post": None}])
    assert acts == []                                             # in flight: reconcile.py


def test_worn_set_is_authored_owner_set_waits():
    j = job(2, holdouts=[{"state": "retired"}, {"state": "retired"}])
    _p, acts = plan(goal(), [j])
    assert kinds(acts) == [("author", 2, None)]
    g = goal()
    g["spec"]["holdout"]["author"] = "owner"
    _p, acts = plan(g, [job(2, holdouts=[])])
    assert kinds(acts) == [("escalate", 2, "DECISION")]
    esc = [{"open": True, "goal": "g", "job_id": 2, "kind": "DECISION"}]
    _p, acts = plan(g, [job(2, holdouts=[])], esc=esc)
    assert acts == []                                               # told once, waits
    _p, acts = plan(g, [job(2)], esc=esc)
    assert kinds(acts) == [("attempt", 2, None)]     # the owner sealed: the wait resolves


def test_goal_done_only_when_every_job_shipped_or_followed_up():
    a = job(2, status="verified", workdir="w")
    shipped = {"job_id": 2, "state": "shipped", "post": {"ok": True}, "follow_up_id": None}
    p, acts = plan(goal(), [a], ships=[shipped])
    assert kinds(acts) == [("done", None, None)]                                 # green
    rb = {"job_id": 2, "state": "rolled_back", "post": {}, "follow_up_id": None}
    p, acts = plan(goal(), [a], ships=[rb])
    assert acts == [] and p.state["g"] == "stuck"         # red: rolled back, no follow-up
    p, acts = plan(goal(status="paused"), [a])
    assert acts == [] and p.state["g"] == "paused"


def test_budget_exhausted_and_measurable():
    b = {"max_task_runs": {"used": 1.0, "limit": 1.0}, "wall_clock": {"used": 10, "limit": 0},
         "max_tokens": {"used": 5, "limit": 10}, "max_cost_usd": {"used": 0, "limit": 0}}
    assert budget.exhausted(b) == ["max_task_runs 1 reached (1 used)"]           # red
    b["max_task_runs"]["used"] = 0.0
    assert budget.exhausted(b) == []                                             # green

    class Cfg:
        data = {"harness": {"name": "command", "command": "x {prompt}", "types": {}}}
    spec = {"limits": {"max_cost_usd": 5, "max_tokens": 0}}
    assert budget.unmeasurable(Cfg, spec) == \
        "budget max_cost_usd cannot be measured on harness command"
    assert budget.unmeasurable(Cfg, {"limits": {"max_cost_usd": 0, "max_tokens": 0}}) is None


def test_claude_usage_is_read_from_its_json_result(tmp_path):
    from konstant import harnesses
    log = tmp_path / "phase.log"
    log.write_text('{"type":"result","total_cost_usd":0.25,"usage":{"input_tokens":100,'
                   '"output_tokens":20,"cache_read_input_tokens":5}}\n')
    assert harnesses.adapter("claude").usage(log) == {"tokens": 125, "cost_usd": 0.25}
    log.write_text("plain text output\n")
    assert harnesses.adapter("claude").usage(log) is None
    assert harnesses.adapter("dsh").usage(log) is None


def test_run_charges_from_manifests(tmp_path):
    (tmp_path / "phases").mkdir()
    for i, sec in enumerate((1.5, 2.5)):
        (tmp_path / "phases" / f"0{i}.json").write_text(json.dumps(
            {"seconds": sec, "harness": "dsh", "log": str(tmp_path / "x.log")}))

    class Cfg:
        data = {"harness": {"name": "dsh", "command": "", "types": {}}}
    assert budget.run_charges(Cfg, tmp_path) == {"wall_s": 4.0, "phases": 2.0}


def test_proc_state_and_stop_file(tmp_path):
    (tmp_path / "var" / "factory").mkdir(parents=True)
    assert proc.state(tmp_path, 1)["state"] == "stopped"
    proc.pid_file(tmp_path).write_text("1\n")              # pid 1 is never this factory
    assert proc.running_pid(tmp_path) is None
    proc.set_stop(tmp_path, "me", "test")
    assert proc.stopped_by(tmp_path)["by"] == "me"
    proc.write_json(proc.heartbeat_file(tmp_path), {"ts": time.time() - 100})
    assert proc.state(tmp_path, 1)["state"] == "stopped"     # no live pid: stopped, not stale
    fh = proc.lock(tmp_path)
    assert fh is not None and proc.lock(tmp_path) is None      # one factory per workspace
    fh.close()
    assert proc.lock(tmp_path) is not None


def test_unit_text_never_enables(tmp_path):
    class Cfg:
        home = tmp_path
    text = unit.text(Cfg)
    assert "ExecStart=" in text and "systemctl" not in text.split("\n", 1)[1]
    assert unit.name(Cfg).startswith("konstant-factory-")
    assert "never runs systemctl" in unit.howto(Path("/x/" + unit.name(Cfg)))


def test_factory_tab_is_read_only_and_renders_text_only():
    """The board's Factory tab (docs/LEVEL5.md 6.4): it reads the two factory routes and renders
    every value with textContent, never as HTML; it writes nothing."""
    static = Path(__file__).resolve().parents[2] / "src" / "konstant" / "board" / "static"
    html, js = (static / "index.html").read_text(), (static / "board.js").read_text()
    assert 'id="tab-factory"' in html and 'id="factory-view"' in html
    assert '"/api/factory/status"' in js and '"/api/factory/goals"' in js
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "method:"):
        assert bad not in js, bad
