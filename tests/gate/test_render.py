"""The gate block (DESIGN §6.3): budget, phases, verdict files, per-type statements."""
from __future__ import annotations

import pytest

from konstant import catalog
from konstant.gate import render

CAT = catalog.load()


def _rec(scen, ttype):
    return scen(ttype=ttype).rec


def test_render_budget(scen):
    rec = _rec(scen, "code")
    blk = render.block(rec, CAT)
    assert render.block_len(blk, rec) <= render.BLOCK_BUDGET
    assert blk.startswith("=== TASK GATE (code) ===") and blk.rstrip().endswith("=== END TASK GATE ===")


def test_dsh_session_block_points_at_its_profiles_within_budget(scen):
    """A dsh session finds the profiles in .dsh/agents/ and starts phases as subagents."""
    rec = _rec(scen, "code")
    blk = render.block(rec, CAT, harness="dsh")
    assert ".dsh/agents/<agent>.md" in blk and "`subagent`" in blk
    assert ".claude/agents" not in blk
    assert render.block_len(blk, rec) <= render.BLOCK_BUDGET


def test_render_budget_red_is_measurable(scen):
    rec = _rec(scen, "code")
    rec["task_padding"] = None
    blk = render.block(rec, CAT) + "x" * render.BLOCK_BUDGET
    assert render.block_len(blk, rec) > render.BLOCK_BUDGET


def test_code_block_lists_the_phases_in_order(scen):
    blk = render.block(_rec(scen, "code"), CAT)
    lines = [ln for ln in blk.splitlines() if ln.startswith("  ") and ". " in ln[:6]]
    agents = [ln.split(". ", 1)[1].split(" ")[0] for ln in lines]
    assert agents == ["architect", "coder", "tester", "reviewer", "architect"]
    for vf in ("TEST-verdict.md", "REVIEW-verdict.md", "ARCH-verdict.md"):
        assert blk.count(vf) == 1, vf


@pytest.mark.parametrize("ttype", CAT.type_names())
def test_every_type_renders_its_mechanics(scen, ttype):
    rec = _rec(scen, ttype)
    blk = render.block(rec, CAT)
    for needle in (f"[type:{ttype}]", rec["out"], rec["judge_cmd"], rec["check_cmd"],
                   "NEVER write, edit or append to a verdict file yourself", "up to 3 cycles",
                   "| BLOCKED |", "never resumed", "ID | claim | STATUS | evidence", "CLEANUP:",
                   "CYCLES.md", f"skill `workflow-{ttype}`", "never spawns agents"):
        assert blk.count(needle) >= 1, needle
    for ph in CAT.verifying(ttype):
        if not (CAT.read_only(ttype) and ph.get("when")):
            assert ph["verdict"] in blk
    assert ("Read-only type" in blk) == CAT.read_only(ttype)
    assert ("proof-of-absence" in blk) == CAT.done_rows(ttype)


def test_unknown_tag_note(scen):
    rec = _rec(scen, "code")
    rec["why"] = "unknown-tag:poetry"
    assert "NOTE: [type:poetry] is not a known type" in render.block(rec, CAT)
