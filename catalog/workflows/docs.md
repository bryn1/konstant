---
description: Run a docs task - documentation written from the artifacts (commits, files, running behaviour), stale sentences fixed in their one home, then an accuracy review against the artifacts. Load when a task is [type:docs] (README, guide, runbook, ADR, changelog, de-staling).
---
## Producer brief (writer)

1. **Artifacts first**: the commits, files, commands and board records the document describes.
   Read the doer's report last and list every divergence from the artifacts.
2. **Grounded or UNVERIFIED**: every number, path, version, command and behaviour is read from the
   artifact or re-run; what cannot be grounded is marked UNVERIFIED with the reason.
3. **Commands in docs are run** before they are published, exactly as written (copy, never
   retype); a command that fails is a finding against the doc or the code.
4. **De-stale** (skill `doc-hygiene`): grep for the names, numbers and claims the change retired and
   fix each in its canonical home; extend existing pages before creating new ones; link new pages
   from where readers look.
5. **Decision records** (skill `adr`) only for choices with two viable options that are costly to
   reverse.

## Review (reviewer)

Pick the load-bearing claims and re-derive them from the artifacts; run the documented commands;
check that nothing the change retired is still claimed anywhere. FIX names each wrong sentence.

## Exit

DONE.md rows per DoD line with the documents and the de-staled sentences, CLEANUP line, the check
exits 0, the job closes with `job review` (by the owner or the verifier, never the identity that filed or claimed it). Work that changed no behaviour needs no doc: say so.
