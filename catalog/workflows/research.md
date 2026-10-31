---
description: Run a research task - prior work first, fetched and quoted sources, a verdict per claim (in general and for this project's environment), then an adversarial review of the claims against their sources. Load when a task is [type:research] (investigate, compare, evaluate, which library or approach).
---
## Producer brief (researcher)

1. **Clarify** if budget, scope, environment or use case is missing (two or three questions at most).
2. **Prior work**: board search, project docs, code; cite and reuse what exists.
3. **Fetch real sources** and quote them (skill `citation-discipline`); a snippet or a title is not
   a source. Verify every cited URL and every cited file path at a pinned ref.
4. **Per-claim verdicts**, never one verdict for the report; separate "true in general" from "true
   for this project's environment" (version, platform, scale). A measurement on other hardware or
   another version is not evidence here: mark it as needing a local measurement.
5. **Answer first**: recommendation and confidence, then the evidence table, then gaps, then what is
   deliberately not recommended and why.

## Review (reviewer)

Re-open the load-bearing sources and try to refute each claim: overstated numbers, wrong domain,
claim not in source, outdated version. Default to RECONSIDER when a load-bearing claim cannot be
checked. A claim whose wording goes beyond its quote (a verdict, a severity, a causal conclusion)
always gets this judgement, however clean its citation mechanics look.

## Exit

DONE.md rows per DoD line pointing at the document and its tagged claims, CLEANUP line, the check
exits 0, the job closes with `job review` (by the owner or the verifier, never the identity that filed or claimed it). Store the verified conclusion where the project keeps
knowledge (its docs or the board job) so the next search finds it.
