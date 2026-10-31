---
description: Run a security task - recon, deterministic scans, flow reasoning, independent confirmation of each finding, ranked report - read-only unless the run is asked to fix. Load when a task is [type:security] (audit, hardening review, threat model).
---
## Phases in practice

1. **Recon** (security agent): map the architecture, trust boundaries, entry points and data
   stores; keep a coverage list of every unit examined, because a strong finding in one area does
   not show another area was looked at.
2. **Scan, then reason** (skills `security-scan-triage`, `security-review`): scanners over the tree
   and the diff; triage by reachability; then trace untrusted input to sinks, authorization order,
   secrets, exposure surfaces, agent-instruction surfaces.
3. **Findings, not verdicts**: `FINDINGS-security.md` with severity, `file:line`, impact, a
   reproduction (sandbox only) or UNVERIFIED, and the fix. Unresolved leads are listed as
   needs-validation with the exact missing fact and no severity; disproved candidates are recorded,
   not forgotten.
4. **Independent confirmation** (reviewer): a different agent tries to disprove each finding and
   writes `REVIEW-verdict.md`; the finder never confirms its own findings.
5. The architect phases run only if the run changed project files (a fix requested in the task).

## Rules

Never scan or exploit a live system; never paste a secret's value; a committed secret's fix
includes rotation. Hardening gaps without an exploit path are notes, not findings. The report is
derived from the confirmed records, not written first.

## Exit

DONE.md rows per DoD line (scope covered, findings file, each CRITICAL/HIGH reproduced or marked
UNVERIFIED), CLEANUP line, the check exits 0; the job closes with the findings path as evidence.
