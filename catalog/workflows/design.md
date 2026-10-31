---
description: Run a design or planning task - a testable goal, prior work, a file-level design with rejected alternatives, a module and step breakdown with a checkable done per step, then an adversarial review of the design. Load when a task is [type:design] (architecture, plan, roadmap, breakdown, data model).
---
## Producer brief (architect)

1. **Testable goal** before anything else:

   ```
   GOAL:       one sentence, what exists at the end
   ACCEPTANCE: the check that proves it (a command, a route, a file, a passing test)
   PREMISE:    the versions, platform and environment the design assumes, as of <date>
   REPLACES:   the running system this replaces, or "nothing"
   RISK:       actuates hardware | moves data | changes a live service | read-only/low
   ```

   If ACCEPTANCE cannot be written as something a tool could check, the goal is not a task yet:
   clarify once. Before building from an old plan, re-check its PREMISE.
2. **Prior work**: board search, docs, code. Extend, do not rebuild.
3. **Design**: approach, the rejected alternative and why, critical files and seams, invariants,
   reuse with paths, cost, blast radius and rollback (skill `architecture-review`). Put the
   cheapest falsifier first: if a quick experiment could kill the idea, plan it (skill `spike`).
4. **Breakdown**: a module table (`module | path | interfaces | depends_on | type | DoD`) and a step
   list where each step is a few minutes to an hour of one agent's work, names its files and its
   check, and states what can run in parallel. Each step becomes a board job.

## Review (reviewer)

Refute the design and the breakdown: does the design solve the reported problem; is each
`depends_on` edge real (does the module need an artifact of the other, or only an interface it can
stub); is any independence claim false (two modules writing the same file); is a step uncheckable;
is there a simpler design; does anything duplicate an existing mechanism.

## Exit

DONE.md rows per DoD line pointing at the design document and the breakdown, CLEANUP line, the check
exits 0, the job closes with `job review` (by the owner or the verifier, never the identity that filed or claimed it); build jobs are filed from the breakdown afterwards.
