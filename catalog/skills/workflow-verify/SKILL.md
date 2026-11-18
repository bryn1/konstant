---
name: workflow-verify
description: Eleven-step verification procedure for workflow outputs - derive claims from the DoD (not the author's summary), verify each claim against an artifact, check the negative side, produce a verdict. Use when verifying that a task or workflow output actually satisfies its Definition of Done.
---

# Workflow verification — does it actually satisfy the DoD?

The job of a verifier is not to check whether the author was diligent. It is to check whether
the deliverable satisfies the Definition of Done. These are different questions.

**The fundamental rule**: derive claims from the DoD (and the task brief), not from the author's
summary of what they did. The author's summary is evidence about effort, not about the result.

## The eleven steps

**Step 1 — List the claims from the DoD.** Read the task brief and the DoD. Write down each
claim as a checkable statement. A vague DoD line like "the feature works" becomes "the endpoint
returns a 200 for a valid request and a 400 for a missing required field". A DoD line with no
artifact to check is UNVERIFIABLE — name it.

**Step 2 — Identify the artifact for each claim.** Each claim should map to a specific artifact:
a file path, an endpoint, a database row, a rendered page element. If a claim has no artifact,
it cannot be verified — that is a gap in the DoD, and it is a finding.

**Step 3 — Verify each claim independently.** Do not read the author's verification. Run the
check yourself. For each claim:
- Name the instrument (command, query, page load, visual check)
- Run it
- Record the output
- Label: VERIFIED | FAIL | BLOCKED

**Step 4 — Check the negative side.** For every behavior the system should reject: does it
actually reject it? See `negative-testing` for the checklist. A claim is not VERIFIED if only
the happy path was tested.

**Step 5 — Check the boundary conditions.** For every numeric limit, state transition, or
constraint in the DoD: test at and around the boundary.

**Step 6 — Grade claimed test coverage.** For each test the author claims as evidence: does
the test actually exercise what it claims to exercise? Can the test stay green while the
feature is broken? See `test-quality-audit`.

**Step 7 — Inspect real state.** Do not read the author's inspection of state — read the state
yourself. The row that was written, the file that was created, the cache that was populated.

**Step 8 — Check deployment if applicable.** If the deliverable is a deployed service: is it
the right version? Does it start on boot? Is it the artifact you tested, not an older one?

**Step 9 — Note what you deliberately did not verify.** Be explicit about scope. A verifier who
tested everything they could is more trustworthy than one who tested everything — because the
latter is usually not true.

**Step 10 — Produce a verdict.**

```
# VERDICT: PASS
```
Only if every DoD line is VERIFIED and the negative side was tested.

```
# VERDICT: FAIL
```
Name each unverified or failing DoD line and the specific evidence (or absence of evidence).

```
# VERDICT: BLOCKED
```
When the check itself could not run — name the exact command, path, or permission that failed.

**Step 11 — Never emit PASS to be agreeable.** A gate that cannot fail is not a gate. If you
could not check a DoD line, it is FAIL (you cannot verify it) or BLOCKED (you cannot run the
check), not PASS.

## Anti-patterns

- **Reading the author's summary instead of the artifact.** A summary is a claim; the artifact
  is evidence. Read the artifact.
- **Testing locally when the claim is about a deployed service.** Test against the actual
  deployment.
- **Skipping the negative cases.** The happy path always passes. The negative cases are where
  bugs hide.
- **Producing a PASS when you only verified some DoD lines.** State which lines were verified
  and which were not.
