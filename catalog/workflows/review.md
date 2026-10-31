---
description: Run an adversarial review of a change, branch or plan - correctness and security findings in parallel, the top findings reproduced by the tester, one ranked synthesis with SHIP, FIX or RECONSIDER. Load when a task is [type:review] (review, audit, critique, post-mortem).
---
## Frame the scope first

Name what is reviewed (commit range, branch, paths or document), what it claims to do, and the DoD
it was built against. A review without a stated claim reviews nothing.

## Dimensions (independent agents, run concurrently)

- **Correctness** (reviewer, `FINDINGS-review.md`): does it do what the task asked, failure modes,
  simpler alternatives, duplicated mechanisms, contract drift between layers (skill
  `contract-audit`), tests that could stay green while broken (skill `test-quality`), file
  hygiene and dead code.
- **Security** (security, `FINDINGS-security.md`): authz, secrets, injection, exposure.
- Optional when the change has UI: a visual and accessibility pass across the touched routes.

The tester then **reproduces the top findings** and writes `TEST-verdict.md`: a finding nobody can
reproduce is downgraded or dropped, with the reason.

## Synthesis

One findings list ranked P0-P4, each classified (skill `findings-triage`) and grounded in a
command and its output, plus one overall call: SHIP, FIX (the minimum change set) or RECONSIDER
(the alternative). If any dimension dissents, show the dissent; never report "reviewed clean" over
a dissent. Confirmed issues become board jobs. State what was deliberately not reviewed.

## Exit

DONE.md rows per DoD line, CLEANUP line, the check exits 0, the job closes with `job review` (by the owner or the verifier, never the identity that filed or claimed it).
