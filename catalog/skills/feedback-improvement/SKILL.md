---
name: feedback-improvement
description: Apply owner or reviewer feedback to an existing skill, profile, or document - classify scope, apply the smallest change that addresses the feedback, and produce an audit trail. Use when applying feedback to a skill or document rather than creating a new one.
---

# Feedback improvement — applying feedback to an existing document

Use this skill when you have received feedback on a skill, profile, or document and need to apply
it systematically without over-engineering the change.

## Steps

1. **Record the feedback verbatim.** Quote the owner's or reviewer's exact words. Never paraphrase
   a ruling before applying it — you will lose precision about what was actually required.

2. **Classify scope.** Is this:
   - A **correction** — something wrong that must be fixed (factual error, broken example, wrong
     instruction)
   - An **addition** — a new rule, section, or example that did not exist
   - A **removal** — something that should be deleted or moved to an archive
   - A **reframing** — the content is correct but the framing or emphasis is wrong
   - A **precision increase** — the content is correct but too vague to be actionable

3. **Apply the smallest change that fully addresses the feedback.** Do not use feedback as an
   excuse to refactor content that was not in scope. Touch only the section the feedback named.

4. **Leave an audit trail.** Either in a commit message, in the document's changelog section, or
   in the frontmatter version bump: record what changed, why (citing the feedback), and when.

5. **Verify the change addresses the feedback.** Re-read the feedback. Does the revised document
   satisfy it? If the feedback named a specific scenario and the document still cannot handle that
   scenario, the change is not done.

## Anti-patterns

- **Rewriting more than the feedback asked for.** The feedback may be small; the temptation to
  "while I'm here" improve adjacent text is how scope creeps.
- **Softening a ruling.** If the feedback is "the rule must be absolute", do not introduce
  exceptions that dilute it.
- **Applying feedback to the wrong version.** Read the current live version before editing. A
  previous session may have already made part of the change, or the document may have drifted.
