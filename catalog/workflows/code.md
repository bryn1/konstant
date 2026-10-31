---
description: Run a code task (feature, fix, refactor, API, script) through placement plan, build, independent test, adversarial review and architecture check until the DoD check is MET. Load when a task is [type:code] or the gate names workflow-code.
---
## Before the first phase

- **Prior work and reuse**: `konstant job search`, grep the project for the mechanism the task may
  already have; extend it rather than build beside it (skill `reuse-first`).
- **Risk**: a change that actuates hardware, moves data or changes a live system gets the full
  independent test and review phases and a kill switch; never an inline verdict by the producer.
- **Replacing a running system** (port, rewrite, migration, cutover): load
  `replace-a-running-system`; its inventory rows become DoD rows.

## Build mode (new behaviour)

1. Architect (open): the placement plan, the files to touch, the interfaces pinned before any code.
   With several modules, pin the cross-module contract in one place first, then build module by
   module; after assembly import every module and call every seam once.
2. Coder: test first, one concern per commit (a commit over about 30 files or 1,500 lines with no
   test file is split), proof that it runs, committed.
3. Tester and reviewer in parallel: the tester proves the DoD against the running code, the reviewer
   tries to refute the design and the diff. Neither re-runs the other's work unless disputing it.
4. Architect (close): `docs/ARCHITECTURE.md` matches the tree, hygiene holds.

For an HTTP API: schema and error shape first (skill `api-design`), then the failing HTTP test,
then the endpoints; assertions on real responses (status AND body) from a running server, error
cases included (422, 404, 409).

## Fix mode (a reported defect)

Same phases, narrower producer brief: reproduce the failure first and keep the reproduction as the
regression test; find the mechanism (one falsifiable hypothesis, tested cheaply) before editing;
fix it where all callers route through; one concern, no opportunistic refactor riding along. The
tester re-runs the original reproduction (red before, green after) and the surrounding suite. Two
honest fix attempts that do not pass: stop and escalate with the evidence of both.

## Exit

DONE.md has one row per DoD line, the `N1` proof-of-absence row and one row per surface (backend,
db, frontend, api contract, tests, docs, deploy; N/A with a reason), every PASS with evidence a
stranger can re-check; the CLEANUP line; then the check exits 0 and the job closes with that
evidence.
