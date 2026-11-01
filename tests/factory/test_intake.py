"""`konstant intake GOAL` end to end (docs/LEVEL5.md 4.2, wave L5-3): a real board, the greeter
target, every intake phase and the scenario writer through the real dsh adapter (stub dsh + the
fake harness's planner / DoD-reviewer / scenario-writer modes), in konstant's jail.

  B3  intake exits 0; the backlog jobs exist, approved (queued), each brief passes `job lint`
  B4  FAKE_HARNESS_MODE=weak-dod -> exit 3 `UNMET: job B2 DoD has no PROBE`, no job filed
  B5  a job's trail: planner (add), dod-reviewer (dod-review SHIP), factory (approve), scenario
      (holdout), pairwise distinct
  B8  `task classify` never returns intake
  B10 `job show` has goal_id and the budget
plus: intake runs once; no jail -> exit 2 before any phase; the scenario writer refused twice ->
exit 4 with a BLOCKED escalation; a non-relocatable harness is refused for the scenario writer."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.factory.conftest import FAKE
from tests.holdout.conftest import make_ws, needs_jail

GOAL = ('[goal]\nid = "greeter"\nproject = "greeter"\ntext = """\nA small greeting library: '
        'greet(name) and a CLI `greet NAME`.\n"""\n[limits]\nmax_attempts = 3\n')


@pytest.fixture()
def iws(tmp_path):
    w = make_ws(tmp_path)
    (w.src / "goal.toml").write_text(GOAL)
    res = w.run("--as", "owner", "goal", "add", w.src / "goal.toml")
    assert res.returncode == 0, res.stderr
    yield w
    w.run("board", "stop")


def intake(w, mode: str = "", harness: str = "dsh", **env):
    e = w.henv(**({"FAKE_HARNESS_MODE": mode} if mode else {}), **env)
    return subprocess.run([sys.executable, "-m", "konstant", "intake", "greeter", "--harness",
                           harness], capture_output=True, text=True, env=e, cwd=str(w.home),
                          timeout=900)


def jobs(w) -> list:
    return w.json("job", "list", "--project", "greeter")


def test_B1_goal_add_prints_and_copies(iws):
    assert (iws.home / "var" / "factory" / "goals" / "greeter.toml").read_text() == GOAL
    g = iws.json("goal", "show", "greeter")
    assert g["status"] == "active" and g["source"] == "file"


@needs_jail
def test_B3_B5_B10_intake_files_reviewed_jobs_with_sealed_holdouts(iws):
    res = intake(iws)
    assert res.returncode == 0, res.stderr[-3000:]
    rows = jobs(iws)
    assert [r["title"][:3] for r in rows] == ["B1:", "B2:"]
    assert all(r["status"] == "queued" for r in rows)
    assert rows[1]["after_id"] == rows[0]["id"]
    run = sorted((iws.home / "var" / "runs").iterdir())[-1]
    for bid in ("B1", "B2"):                                         # B3: every brief lints clean
        lint = iws.run("job", "lint", run / "out" / "jobs" / f"{bid}.md")
        assert lint.returncode == 0, lint.stdout + lint.stderr
    for r in rows:
        j = iws.json("job", "show", str(r["id"]), "--trail")
        actors = [(t["actor"], t["kind"]) for t in j["trail"]]
        assert actors == [("planner", "status"), ("dod-reviewer", "dod-review"),   # B5
                          ("factory", "approval"), ("scenario", "holdout")], actors
        assert len({a for a, _k in actors}) == 4
        assert j["goal_id"] and j["goal"] == "greeter"                              # B10
        assert j["budget"] == {"max_attempts": 3, "goal_limits": {}}
        assert [h["state"] for h in j["holdouts"]] == ["sealed", "sealed"]
        assert {h["author_label"] for h in j["holdouts"]} == {"scenario"}
    g = iws.json("goal", "show", "greeter")
    assert g["intake"] == "filed"
    ev = [json.loads(ln) for ln in (iws.home / "var" / "factory" / "events.jsonl").read_text()
          .splitlines()]
    assert [e["event"] for e in ev] == ["FILED"]
    manifests = {p.name: json.loads(p.read_text()) for p in (run / "phases").glob("*.json")}
    assert any("planner" in n for n in manifests) and any("reviewer" in n for n in manifests)
    again = intake(iws)                                             # intake runs once per goal
    assert again.returncode == 2 and "taken in already" in again.stderr


@needs_jail
def test_intake_phases_act_as_planner_and_dod_reviewer(iws):
    """The planner phase acts as `planner`, the DoD review phase as `dod-reviewer` (types.yaml
    `identity`; the phase manifest records it), so each reads only its own token (LEVEL5 2.1)."""
    assert intake(iws).returncode == 0
    run = sorted((iws.home / "var" / "runs").iterdir())[-1]
    got = {json.loads(p.read_text())["agent"]: json.loads(p.read_text())["identity"]
           for p in (run / "phases").glob("*.json")}
    assert got == {"planner": "planner", "reviewer": "dod-reviewer", "orchestrator": "planner"}


@needs_jail
def test_B4_weak_dod_files_nothing(iws):
    res = intake(iws, "weak-dod")
    assert res.returncode == 3, res.stderr[-2000:]
    assert "UNMET: job B2 DoD has no PROBE" in res.stdout
    assert jobs(iws) == []
    assert iws.json("goal", "show", "greeter")["intake"] == "refused"
    ev = (iws.home / "var" / "factory" / "events.jsonl").read_text()
    assert '"event": "BLOCKED"' in ev and "B2 DoD has no PROBE" in ev


@needs_jail
def test_scenario_writer_refused_twice_blocks_the_job(iws):
    res = intake(iws, "weak-scenario")
    assert res.returncode == 4, res.stderr[-2000:]
    rows = jobs(iws)
    assert len(rows) == 2 and all(r["status"] == "queued" for r in rows)
    j = iws.json("job", "show", str(rows[0]["id"]), "--trail")
    assert j["holdouts"] == []                                # nothing sealed: the claim waits
    esc = [t for t in j["trail"] if t["kind"] == "escalation"]
    assert esc and esc[0]["actor"] == "factory" and "holdout-authoring BLOCKED" in esc[0]["body"]
    assert "VACUOUS" in esc[0]["body"] and "khc-" not in esc[0]["body"]
    claim = iws.run("job", "claim", str(rows[0]["id"]))
    assert claim.returncode == 1 and "no holdout sealed" in claim.stderr


@needs_jail
def test_scenario_writer_refused_on_a_harness_konstant_cannot_relocate(iws):
    res = intake(iws, harness=FAKE)
    assert res.returncode == 4, res.stderr[-2000:]
    assert "cannot relocate" in res.stderr
    assert all(not iws.json("job", "show", str(r["id"]))["holdouts"] for r in jobs(iws))


def test_intake_without_the_jail_exits_2_before_any_phase(iws):
    res = intake(iws, KONSTANT_NO_JAIL="1")
    assert res.returncode == 2 and "holdouts need a confined phase" in res.stderr
    assert not (iws.home / "var" / "runs").exists() or not any((iws.home / "var" / "runs").iterdir())
    assert iws.json("goal", "show", "greeter")["intake"] == "none"


@pytest.mark.parametrize("text", ["intake the backlog for the goal",
                                  "[type:intake] plan the goal greeter into jobs",
                                  "plan the intake of goal greeter: write the backlog file"])
def test_B8_classify_never_returns_intake(iws, text):
    res = iws.json("task", "classify", text)
    assert res["type"] != "intake", res


def test_intake_refused_inside_a_task_run(iws):
    res = iws.run("intake", "greeter", env=iws.henv(KONSTANT_IN_TASK="1"))
    assert res.returncode == 1 and "not available inside a task run" in res.stderr
