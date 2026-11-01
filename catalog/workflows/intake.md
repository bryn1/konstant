---
description: Run a level-5 intake - one goal turned into a backlog of board jobs whose briefs carry a DoD every row of which a PROBE settles, reviewed by a separate DoD-reviewer identity, then filed by code. Load when a run is `konstant intake GOAL` ([type:intake] is reachable only that way).
---
## Producer brief (planner)

1. Read the goal (the task text), the target project read-only (its README, its layout, its tests)
   and nothing else. The backlog extends what exists; it never rebuilds it.
2. Write `OUT/BACKLOG.md` (`B<n> | <type> | <title> | after:B<m>` per row, `-` for no dependency)
   and one brief per row, `OUT/jobs/B<n>.md`: a title line, the work, then `DoD:` with rows a
   verifier can settle, at least one `PROBE: <read-only command> => <regex>` per brief, and paths
   of the result as `{workdir}/<path>`.
3. Keep jobs few and each one finishable by one producer run; a job that needs another's result
   says `after:` that row.

## DoD review (reviewer, acting as the dod-reviewer identity)

Read the goal, `BACKLOG.md` and every brief. For each job decide: does its DoD prove the part of
the goal it claims; can every row be settled by its PROBE lines; is anything the goal asks for
missing from every job; is a job unfinishable alone. Write `DOD-verdict.md`: one line per job,
`B<n> | SHIP | <why>` or `B<n> | FIX | <what to change>`, then the `# JUDGED:` line, then
`# VERDICT: SHIP` (every job SHIP) or `# VERDICT: FIX`. FIX sends the planner back with your
lines; the JUDGED pin makes a brief changed after your review count as unreviewed.

## Exit (code, never a model)

The DoD check must be MET; then konstant re-checks every brief deterministically (no lint flag, at
least one PROBE, known types, `after:` only to earlier rows, within max_jobs), files the jobs under
the goal's project as the planner identity, posts each job's dod-review as the DoD reviewer,
approves each as the factory identity, and has the scenario writer seal each job's holdouts. A
brief that fails a rule files nothing.
