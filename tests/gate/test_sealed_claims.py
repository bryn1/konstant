"""A phase never attests what it cannot see (L5-6 live finding 2).

Live: the intake's close-out wrote `P8 | the research result for this run persists in the research
store | BLOCKED | ...` - a careful model that cannot read the sealed research store - and the DoD
check took the row as written: BLOCKED, the whole intake refused, nothing filed. konstant checks
that store itself (rule `research`), so a row about a sealed store is no attestation: it is
ignored with a warning (never blocks, never counts as the PASS), and the close-out prompt says so.
Red twins: the same row about the project's own files still blocks; a job's DoD-<n> row is never
ignored; a run whose research step did not run is still UNMET by the research rule itself."""
from __future__ import annotations

from konstant import catalog
from konstant.gate import check, runner
from konstant.gate.rules import done
from tests.gate.conftest import done_text

LIVE_ROW = ("P8 | the research result for this run persists in the research store (var/research/)"
            " | BLOCKED | the close-out cannot read var/research/ to confirm it\n")


def test_a_blocked_row_about_the_research_store_does_not_block_green(scen):
    s = scen().good()
    s.done(done_text(LIVE_ROW))
    code, lines, warns, _f = s.check()
    assert code == check.MET, lines
    assert any("P8 (BLOCKED) is about a sealed store and is ignored" in w for w in warns), warns


def test_the_same_row_about_the_project_still_blocks_red(scen):
    s = scen().good()
    s.done(done_text("P8 | the result file persists in the project (results/) | BLOCKED | the "
                     "close-out cannot confirm it\n"))
    code, lines, _w, _f = s.check()
    assert code == check.BLOCKED and any(ln.startswith("BLOCKED: P8") for ln in lines), lines


def test_a_sealed_row_never_counts_as_the_pass_row_red(scen):
    s = scen().good()
    s.done("ID | claim | STATUS | evidence\nD1 | x | N/A | not asked\nH1 | the holdout store "
           "holds 2 sealed scenarios | PASS | konstant holdout list: 2 sealed\n"
           "CLEANUP: NONE-NEEDED\n")
    assert any("no PASS row" in ln for ln in s.check()[1])


def test_every_sealed_store_is_recognised_and_job_dod_rows_never_are():
    for claim in ("the research store has the result", "var/research/r1/result.json exists",
                  "the holdout store is sealed", "var/holdout/2 holds H1", "sealed holdouts pass",
                  "the memory vault has the note", "var/memory index updated", "sealed store ok"):
        assert done.sealed_claim("P1", claim), claim
    for claim in ("the research document cites 3 sources", "README documents the CLI",
                  "holdout hints are redacted in the log", "memory use stays under 1 GB"):
        assert not done.sealed_claim("P1", claim), claim
    assert not done.sealed_claim("DoD-1", "the research store is never readable by a phase")


def test_research_is_still_checked_mechanically_red(scen):
    """Ignoring the row takes nothing away from konstant's own check of the store."""
    s = scen().good()
    s.rec["card"] = {"research_required": True}
    s.save()
    s.done(done_text(LIVE_ROW))
    code, lines, _w, _f = s.check()
    assert code == check.UNMET and any("research step" in ln for ln in lines), lines


def test_the_close_out_prompt_scopes_its_claims_green(tmp_path):
    cat = catalog.load()
    rec = {"type": "intake", "out": str(tmp_path / "out"), "judge_cmd": "j", "task": "t",
           "project": None, "intake": True, "goal": "g"}
    pr = runner.PhaseRunner.__new__(runner.PhaseRunner)
    pr.rec, pr.cat, pr.runs, pr.cycles, pr.acceptance, pr.profiles = rec, cat, {}, [], "", {}
    ph = {"n": 0, "agent": "orchestrator", "step": None, "verdict": None, "task": "close-out"}
    text = pr.prompt(ph, None, "", closeout=True)
    assert runner.CLAIM_SCOPE in text and "var/research/" in text
    phase = pr.prompt({"n": 1, "agent": "planner", "task": "plan"}, None, "", closeout=False)
    assert runner.CLAIM_SCOPE not in phase
