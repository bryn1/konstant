"""Wave L5-L2: the "for the next review" items of LEVEL5 "L5-L as built" that could block a live
goal, each as a must-fail test (red on 237521d) with its twin.

Finding 2: the scenario writer's held-out lint read its own job's brief and the goal text, not
the goal's OTHER jobs: two held-out literals of job 1.2 stood verbatim in job 1.1's DoD, which
every phase reads on the board, so they were not held out from job 1.2's producers either (and a
phase that stored job 1.1's DoD as a memory note was refused as a leak).

Finding 1: a producing phase that ended rc 0 without doing anything (run 1's 11 s planner) passed
as a cycle: the verifier then judged the unchanged work again and the cycle was spent. It is now
retried once in its cycle, as a crashed verifier is (17d608a)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.holdout.conftest import BRIEF, H1

FAKE = f"{sys.executable} {os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'fake_harness.py')} {{prompt_file}}"

SIBLING_DOD = "DoD:\n- the CLI prints hello Ada for `greeter Ada`\n"


class Board:
    """The two reads public_text makes: the goal (with its job listing) and each job."""

    def __init__(self, jobs: dict, text: str = "greet by name, with a CLI and a README"):
        self.jobs, self.text, self.paths = jobs, text, []

    def get(self, path):
        self.paths.append(path)
        if path == "/api/goals/7":
            return {"spec": {"goal": {"text": self.text}},
                    "jobs": [{"id": i, "title": j["title"]} for i, j in self.jobs.items()]}
        return self.jobs[int(path.rsplit("/", 1)[1])]


def jobs() -> dict:
    return {1: {"id": 1, "title": "B1 greet by name and a CLI", "brief": "add the CLI",
                "acceptance": SIBLING_DOD, "goal_id": 7},
            2: {"id": 2, "title": "B2 the README", "brief": "document it",
                "acceptance": "DoD:\n- README.md shows the usage\n", "goal_id": 7}}


def test_F2_a_sibling_jobs_dod_is_not_held_out_red():
    """Red on 237521d: goal_text() was the goal's own text only, so H1 (expects `hello Ada`) was
    sealed for job 2 although job 1's DoD shows `hello Ada` to every producer."""
    from konstant.holdout import lint, store
    js = jobs()
    public = store.goal_text(Board(js), js[2])
    assert "hello Ada" in public and "document it" not in public, public
    sc = lint.parse(lint.with_canary(H1.encode()), "H1")
    found = lint.lint(sc, js[2]["brief"], js[2]["acceptance"], goal=public)
    assert any(r.startswith("NOT HELD OUT: H1") and "another of its jobs" in r for r in found), found


def test_F2_twin_a_literal_no_job_shows_is_still_held_out():
    from konstant.holdout import lint, store
    js = jobs()
    js[1]["acceptance"] = "DoD:\n- the CLI greets the name it is given\n"
    public = store.goal_text(Board(js), js[2])
    sc = lint.parse(lint.with_canary(H1.encode()), "H1")
    assert not lint.lint(sc, js[2]["brief"], js[2]["acceptance"], goal=public)
    assert not lint.lint(sc, BRIEF.replace("'world'", "'x'"), "", goal="")


def test_F2_the_writers_pre_check_and_prompt_see_the_siblings_red(tmp_path):
    """The writer's own pre-check reads `.konstant-draft.json`: it must carry the same public text
    the seal lints against, and the prompt names the other jobs (red: neither did)."""
    from konstant.holdout import author, draft, store
    js = jobs()
    text, others = store.public_text(Board(js), js[2])
    p = draft.write_context(tmp_path, {**js[2], "display_id": "1.2"}, 1, text + "\n" + others)
    f = tmp_path / "a.scenario"
    f.write_text(H1)
    rows = draft.check([f], draft.read_context(p))
    assert any("another of its jobs" in r for r in rows["drafts"][0]["reasons"]), rows
    body = author.prompt("profile", {**js[2], "display_id": "1.2"}, text, tmp_path, tmp_path, 1,
                         others=others)
    assert "## The goal's other jobs" in body and "hello Ada" in body


def test_F2_twin_a_job_of_no_goal_and_an_unreadable_goal():
    from konstant.holdout import store

    class Down:
        def get(self, path):
            raise ConnectionError("board unreachable")
    assert store.public_text(Down(), {"id": 3, "goal_id": None}) == ("", "")
    assert store.public_text(Down(), {"id": 3, "goal_id": 7, "title": "t"}) == ("t", "")


# --- finding 1: an empty producing phase -------------------------------------------------------

def _run(hws, mode: str):  # noqa: F811
    env = hws.henv(FAKE_HARNESS_MODE=mode, KONSTANT_NO_JAIL="1") if mode else \
        hws.henv(KONSTANT_NO_JAIL="1")
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet(name)", "--project", "greeter", "--harness",
                          FAKE], capture_output=True, text=True, env=env, timeout=900,
                         cwd=str(hws.home))
    rd = sorted((hws.home / "var" / "runs").iterdir())[-1]
    ms = [json.loads(p.read_text()) for p in sorted((rd / "phases").glob("*.json"))]
    return res, ms


def test_F1_an_empty_producing_phase_is_retried_once_in_its_cycle_red(hws):  # noqa: F811
    """Red on 237521d: the coder's empty run passed as its phase; the run then needed a resume
    (a cycle) to get the work it never did."""
    res, ms = _run(hws, "idle-once")
    assert "changed nothing in OUT or the project; retried once" in res.stderr, res.stderr[-3000:]
    assert res.returncode == 0 and "resume" not in res.stderr, res.stderr[-3000:]
    coder = [m for m in ms if m["agent"] == "coder"]
    assert len(coder) == 1 and coder[0]["retried"] and coder[0]["created"], coder


def test_F1_twin_a_producing_phase_that_did_its_work_is_not_retried(hws):  # noqa: F811
    res, ms = _run(hws, "")
    assert res.returncode == 0, res.stderr[-3000:]
    assert "retried once" not in res.stderr
    assert not any(m.get("retried") for m in ms)
