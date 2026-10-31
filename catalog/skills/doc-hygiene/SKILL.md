---
name: doc-hygiene
description: Work is done when the docs stop lying - name the sentences your change made untrue, fix them in their one canonical home, delete the old claim, grep for retired names and numbers, re-check present-tense status lines, and verify the de-stale like any other change. Load at the close of any change that altered behaviour, configuration, names or numbers.
---
# Doc hygiene: the docs stop lying

A stale doc is worse than a missing one: a missing doc makes the next reader look; a stale doc makes
them act on something untrue with full confidence.

## Before you call a change done

1. **Name what the change made untrue.** Not "did I document my work" but "which existing sentence,
   somewhere, is now wrong?" A changed value, default, version, name, path or behaviour almost
   always has an old statement somewhere.
2. **Fix it in its one canonical home and delete the old claim.** Facts live in one place (the
   architecture doc, the README, the runbook, the config reference, the decision record). Never
   leave a correction beside the thing it corrects: readers find either one.
3. **Grep past the obvious**: the retired names and numbers (`git grep -n "<old name>"`), every
   `STATUS:` line, every present-tense claim about something running ("the server on port N is
   up"), every "current" table column. A present-tense liveness claim needs a re-runnable check
   beside it, not a dated sentence.
4. **A retired claim is CONTRADICTED, not doc debt.** When a feature, scope or count is removed, the
   same change rewrites or deletes every surviving mention, UI copy included.
5. **Other knowledge stores rot too.** Wherever the project keeps notes, memories or indexes, look
   up the topic first, then update or supersede the stale entry instead of adding a near-duplicate.
   Never two live entries that contradict each other.
6. **Verify the de-stale**: re-run the grep (zero hits for the retired claim), re-read the edited
   sentence in place. An edit you did not check is a claim, not a change.

## Versions, not overwrites

When a document of record is replaced, the new version is current and the old one is kept, marked
`SUPERSEDED <date>: see <new path>` on its first line (or left to git history for ordinary files).
Never silently rewrite a record others may have cited.

## What does not need this

Read-only research or analysis that changed nothing. Say so and move on; manufactured doc churn is
its own failure.

## The one-line test

Would the next agent, reading the docs as they now stand, believe something that is no longer true?
If yes, you are not finished.
