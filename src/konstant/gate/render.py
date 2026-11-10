"""The gate block (DESIGN §6.3): the RUN-SPECIFIC mechanics of a typed task, printed before the
task text. Standing doctrine lives in the agent profiles and the `workflow-<type>` skill; the
block states only what this run needs: type, phases with agent + verdict file, OUT, the judge and
check commands, the DONE.md shape, the cycle cap with BLOCKED rows, the git last mile.
Budget: BLOCK_BUDGET characters for the `code` block, measured with the install-specific paths
(python executable, run dir, OUT) normalised to fixed tokens, so the budget measures rule text."""
from __future__ import annotations

import sys

BLOCK_BUDGET = 3300


def _phase_lines(rec: dict, cat) -> list:
    out, shown = [], 0
    for p in rec["phases"]:
        if rec.get("read_only") and p.get("when") == "changed":
            continue
        shown += 1
        who = p["agent"] + (f" ({p['step']})" if p.get("step") else "")
        if p.get("parallel") and shown > 1:
            who += f" (may run in parallel with {shown - 1})"
        what = (f"{p['verdict']}: " if p.get("verdict") else "") + p.get("task", "")
        out.append(f"  {shown}. {who} -> {what}")
    return out


PROFILES = {
    "claude": "(.claude/agents/<agent>.md)",
    "dsh": ("(.dsh/agents/<agent>.md: start each phase as a `subagent` whose prompt is that file,\n"
            "then the phase brief)"),
}


def block(rec: dict, cat, harness: str = "claude") -> str:
    """`harness`: where the orchestrating session finds the agent profiles (PROFILES)."""
    t = rec["type"]
    where = PROFILES.get(harness, "(catalog/agents/<agent>.md + AGENTS.md doctrine)")
    cap = int(rec.get("gate", {}).get("max_cycles", 3))
    note = ""
    if str(rec.get("why", "")).startswith("unknown-tag:"):
        tag = rec["why"].split(":", 1)[1]
        note = (f"NOTE: [type:{tag}] is not a known type ({', '.join(cat.type_names())}); the "
                f"words classified it as [type:{t}]. Re-send with a known tag if that is wrong.\n")
    ro = ("Read-only type: the architect opens and closes (ARCH-verdict.md) only if this run "
          "changes a project file; otherwise DONE.md carries `ARCH | architecture doc matches "
          "reality | N/A | this run changed no project file`.\n") if rec.get("read_only") else ""
    rows = ("\n+ an `N1` proof-of-absence row and one `S<n> | surface <name> | ...` row per "
            f"surface\n({', '.join(rec['done_rows']['surfaces'])})") if rec.get("done_rows") else ""
    exer = " and calls into every .py source file in OUT" if rec.get("exercise") else ""
    build = cat.types[t]["deliverable"] == "build" or t == "test"
    hyg = ("File hygiene: a source file over 400 lines, or a project file this run grows past "
           "600,\nneeds a reason in its first 5 lines (skill `coding-discipline`).\n") if build else ""
    phases = "\n".join(_phase_lines(rec, cat))
    dod = ""
    if rec.get("job") and rec.get("acceptance"):
        from konstant.board.dod import dod_rows
        ids = [f"  DoD-{i} | {r[:100]}" for i, r in enumerate(dod_rows(rec["acceptance"]), 1)]
        if ids:
            dod = ("The job's DoD rows; DONE.md answers each with its ID (PASS or BLOCKED, never "
                   "N/A):\n" + "\n".join(ids) + "\n")
    return f"""=== TASK GATE ({t}) ===
{note}This is a [type:{t}] task. Run it as phases, one agent profile per phase
{where}; a phase agent is a leaf and never spawns agents. Workflow and
standing rules: skill `workflow-{t}`. Phases:
{phases}
{ro}OUT, the ONE directory the DoD check reads: {rec['out']}
Verdicts: each verifying phase writes its own file in OUT ending with exactly one
`# VERDICT: {"|".join(w for ws in rec["verdict_words"].values() for w in ws)}` line; as its LAST step it runs
`{rec['judge_cmd']}` and puts the printed `# JUDGED: <sha>` line directly above
the verdict line. NEVER write, edit or append to a verdict file yourself.
Loop: FAIL, FIX or RECONSIDER re-runs the producer with that verdict file, then the verifiers
again, each writing a NEW file (-c2, -c3); up to {cap} cycles. Still not PASS after {cap}, or a
verifier says BLOCKED: one DONE.md row per claim that could not be verified,
`Dn | <claim> | BLOCKED | <why; last verdict file>` - the check then ends BLOCKED, never resumed.
DONE.md in OUT: `ID | claim | STATUS | evidence` per DoD claim, STATUS PASS|FAIL|BLOCKED|N/A|
UNVERIFIED, evidence = a command and its captured output, a path or a sha{rows};
plus one `CLEANUP: <what was moved/removed, where>` or `CLEANUP: NONE-NEEDED` line. Claim only
what you can read: konstant's sealed stores (var/research/, var/holdout/, the memory vault) are
checked by the check itself, and a row about them is ignored.
{dod}Keep CYCLES.md in OUT (cycle | trigger | action | outcome).
Git last mile: commit the deliverable; no untracked file created outside OUT (scratch goes
under OUT/.tmp/); no unfinished-work markers added; changed test files pass; pytest in OUT
passes{exer}.
{hyg}Check: `{rec['check_cmd']}` (0 MET, 3 UNMET, 4 BLOCKED). Done = MET.
=== END TASK GATE ===
""" + card_text(rec)


CARD_MARK = "=== INTAKE CARD"


def card_text(rec: dict) -> str:
    """The run's intake card (konstant/triage/card.py), after the block: data, not rule text."""
    if not rec.get("card"):
        return ""
    from konstant.gate.record import konstant_cmd
    from konstant.triage import card as card_mod
    cmd = konstant_cmd("task", "research", rec["run_dir"]) if rec.get("mode") == "interactive" \
        else ""
    text = card_mod.render(rec["card"], research_cmd=cmd)
    t = rec["card"]["tier"]["name"]
    if t in ("fanout", "max"):
        text += ("\nFAN-OUT: split the work into independent parts (one per file or module the "
                 f"card names) and run at most {rec['card']['tier']['agents']} part(s) at once, "
                 "one `konstant task gate` per part; never more than the cap (skill `fan-out`).")
    elif t == "factory":
        text += ("\nFACTORY: a long-running goal; propose it as a goal (`konstant goal add - "
                 "--from-chat`) instead of running these phases in the session, or re-send with "
                 "[tier:agent] to run it once.")
    return text + "\n"


def block_len(blk: str, rec: dict) -> int:
    """The length BLOCK_BUDGET compares: install-specific paths replaced by fixed tokens."""
    blk = blk.split(CARD_MARK, 1)[0]          # the budget measures rule text, not the card
    norm = blk.replace(sys.executable, "PY").replace(str(rec.get("run_dir", "")), "RUN")
    return len(norm.replace(str(rec.get("out", "")), "OUT"))

