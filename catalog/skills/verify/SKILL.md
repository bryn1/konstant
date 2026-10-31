---
name: verify
description: Prove a claim is real - derive the claims from the task's DoD, run the real check, assert on domain state, label every result, fill DONE.md, and never let the author grade its own work. Load before calling any work done, when writing DONE.md or a verdict, or when deciding whether a closed job really holds.
---
# Verify: prove the claim, not the pulse

A 200 from an empty shell is a FAIL. Verification proves that the specific thing claimed exists and
works, from artifacts, by someone other than the author.

## 1. Derive the claims (task first)

1. Every line of the task's DoD is a claim, whether or not the producer mentions it. A DoD line the
   result never mentions is checked first: the classic false completion is a criterion nobody tested.
2. Then the producer's concrete claims: exact files, routes and methods, tables and row counts,
   selectors and text.
3. Build types add one row per surface (backend, db, frontend, api contract, tests, docs, deploy),
   each PASS or N/A with a reason, and at least one proof-of-absence row: a forbidden behaviour shown
   impossible by a check you ran (`N1 | a second payment on a paid invoice is refused | PASS | POST
   twice -> 409`).
4. A replacement of a running system adds its inventory, consumer, rollback and retirement rows
   (skill `replace-a-running-system`). A change that removed a feature adds the retired claims: grep
   for them; a claim that outlives its implementation is CONTRADICTED.

Vague claims ("auth works") cannot be verified: push back for a checkable one.

## 2. Run the real check, capture the output

- **Database**: count or select the rows that only exist if the code worked.
- **API**: request the real endpoint and assert on the body (a record id, a rendered value), not
  only the status.
- **File**: assert on its specific content, not its existence.
- **CLI**: run the real binary; assert exit code, output and resulting files.
- **UI**: drive the page in a browser (skill `exploratory-qa`); curl is not UI evidence.
- **Build or refactor**: every new function has a live caller; no file grew past the hygiene limits.
- **A gate or monitor you add**: a planted red and one real run (skill `test-quality`).
- **Runtime chain** when behaviour depends on running: build or install from the real path, start,
  health check, the critical journey end to end, then inspect the resulting state. The running
  artifact reports the version or commit you claim.
- **Reproducible** is a transcript: clone into an empty directory, run the README's commands exactly
  as written, record each exit code. Otherwise report WORKED IN CURRENT WORKSPACE.
- **Upgrade-safe** means booting the new code against a copy of the existing state, not a fresh
  database.

Save long outputs as files under `OUT/evidence/` and cite the path; a quote alone is weak evidence.

## 3. Label and record

Labels map to DONE.md statuses: VERIFIED -> `PASS` (evidence filled), contradicted -> `FAIL`,
inferred or unchecked -> `UNVERIFIED`, could not run -> `BLOCKED` (name the command or path).

```
ID | claim | STATUS | evidence
D1 | <DoD line, verbatim> | PASS | out/evidence/d1-pytest.log (12 passed)
S3 | surface db | N/A | no migration or schema file in git diff --stat
N1 | duplicate submit is refused | PASS | second POST -> 409, row count stays 1
CLEANUP: NONE-NEEDED
```

A row whose only content is "the verdict file says PASS" is not a claim. Live state the verifier
must re-check later (a service active, a commit pushed) goes into the job's evidence as
`PROBE: <read-only command> => <regex>` using the allowlisted shapes (`konstant job lint` names
refused lines before you file).

## 4. The verifier is never the author

The agent that built it never grades it. Risky changes (hardware, data moves, live services) get an
independent verifier with no producer context; if one cannot run, the job is BLOCKED, not verified
inline. The verifier plants one fault of its own choosing, confirms the evidence goes red, restores
it, and records it. Default to FAIL when a claim cannot be verified.

## 5. Bounded loop, then close

A FAIL goes back to the producer with the specific findings; the re-check is narrow (the failing
check, not the whole suite) but still counts as a cycle. After three cycles stop and escalate with
the claim, the failed checks and their output, what changed each round, and what remains
unverified. Close only on proof: the evidence file carries a real `VERIFY_EXIT=0`; `verified` is set
by `konstant verify` alone. End every report with what you deliberately did NOT check.
