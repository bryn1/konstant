---
name: failure-taxonomy
description: The ways builds that were reported done turned out not to work - contract drift, look-alike APIs, zero collected tests, claims without evidence, mocks, stale deploys, untested acceptance lines - with the check that catches each. Load before claiming a build done or when reviewing one.
---
# Failure taxonomy: how "done" builds actually fail

Check work against each class before calling it done.

1. **Cross-file contract drift.** Signatures, dict shapes and return types agreed in someone's head
   and never pinned: one file calls `score(df, info, price)`, another `score(info, df)`. Check: pin
   the interface in one place before fanning out; after assembly import every module and call every
   cross-file seam once.
2. **Look-alike API confusion.** Two libraries ship similar components with different parameters.
   Check: verify against the docs or signature of the one you imported, never from memory.
3. **"Tested" with zero tests collected.** Files exist, nothing matches the collector. Check: paste
   the summary line with its count; `no tests ran` is not tested.
4. **The claim without evidence.** "Built and tested" with nothing pasted. Check: CHANGED (diffstat),
   RAN (exact command, output, exit code), PROVES (which DoD line), GATE (who verified).
5. **The environment as an assumption.** Dependencies installed into another interpreter; a tool
   present but broken; `~` unexpanded in a script. Check: run the entry point with the project's own
   interpreter and paste which one ran.
6. **The test hits a mock.** Check: break the real function and re-run; a test that stays green
   proved nothing.
7. **The source is not in the build.** The edited file is not what runs (wrong module path, not
   imported, excluded from the bundle). Check: find the change in the built or served artifact.
8. **Frontend/backend contract mismatch.** Each side passes its own tests; field names or routes
   disagree. Check: one real request from the real client against the running server.
9. **Stale build or deploy.** The fix is committed, the served build is older. Check: compare the
   served version, asset hash or commit with the one you claim.
10. **The acceptance line nobody tested.** The author verified what they built, not what was asked.
    Check: derive claims from the task's DoD first; an unevidenced DoD row is UNVERIFIED.
11. **Unported side effects.** A replacement matched the old system on the compared output and
    silently dropped everything else it did. Check: skill `replace-a-running-system`.
12. **Dead capability.** Ported or new code that no live path calls. Check: every new function has a
    live caller (skill `coding-discipline`).
13. **Guessed inputs.** A measured value replaced by an estimate, a proxy or a hard-coded offset.
    Check: each input traces to the source the old system measured.

**The one-line version:** done means interfaces pinned before fan-out, every seam executed, the test
summary pasted, the entry point run from its own environment, and classes 6-10 checked against the
artifact that actually runs.
