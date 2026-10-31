---
name: citation-discipline
description: Cite sources honestly - fetch before citing, confirm the identifier, quote the supporting sentence, tag each source (VERIFIED, OVERSTATED, WRONG-DOMAIN, WRONG-SOURCE, CLAIM-NOT-IN-SOURCE, PLAUSIBLE-UNCHECKED, OUTDATED), pin repository paths to a ref, and fetch in a sensible order. Load whenever a report, design or doc cites anything.
---
# Citation discipline: fetch, then quote

"VERIFIED" is earned, not a default. Real sources get overstated, come from the wrong field, or say
the opposite of the claim built on them.

## The steps, in order

1. **Fetch the actual source** (below). Never cite from memory, a title, a URL slug or a search
   snippet. If the fetch fails, the source takes the lowest applicable tag.
2. **Confirm existence**: the fetched page shows the exact identifier you cite (title, authors,
   version, paper id, repository slug, year). Otherwise WRONG-SOURCE or PLAUSIBLE-UNCHECKED.
3. **Confirm support**: the fetched text contains the sentence or number behind your claim. Write
   it as a direct quote. A weaker, narrower or caveated statement downgrades the tag.
4. **Write the tag and the quote**:

   ```
   [VERIFIED] Source - what it is.
   "Exact supporting sentence from the fetched text." - Author, year / version.
   [OVERSTATED] Source - "the actual finding" (your claim was X; the source says Y).
   ```

## Tags

VERIFIED (fetched, exists, quote supports the claim) · OVERSTATED (real but narrower or more
caveated) · WRONG-DOMAIN (real, different field) · WRONG-SOURCE (the identifier resolves to
something else) · CLAIM-NOT-IN-SOURCE (real, does not say it) · PLAUSIBLE-UNCHECKED (could not
fetch; never VERIFIED) · OUTDATED (superseded by a newer version or study; name it).

## Rules

- Default to PLAUSIBLE-UNCHECKED. A statistic matches the source exactly; a rounded or generalised
  number is OVERSTATED.
- **A real repository does not make its file paths real.** Enumerate the tree at the ref you read
  (`git ls-tree -r --name-only <sha>`), pin that commit, and quote the cited lines. If you cannot,
  cite the repository without paths or line numbers.
- **Cite or abstain**: an unsupported claim labelled as such is worth more than a nearby source
  that is probably equivalent.
- **Absence is a claim too**: before "not found" or "the repo has no X", run the instrument that
  would show it present and name its blind spot.
- A claim whose wording goes beyond its quote (a verdict, a severity, a causal conclusion) is
  judgement, not fact, however clean its citation; it stays open for adversarial review.
- Re-fetch before re-using a quote from an earlier report; check author affiliations and star
  counts live, never from memory.

## Fetch order

1. A plain HTTP fetch of the page (the harness's fetch tool or `curl -sL`), reduced to text; or a
   scraper that returns clean markdown for article pages.
2. If that returns little (login wall, cookie banner, heavy JavaScript), a real browser: navigate,
   accept the banner, read the rendered text. A login wall is a stop, not something to get around.
3. Papers: the abstract page or the publisher record; repositories: the README or the cited file at
   a pinned commit; packages: the registry page for the exact version.
4. Still unreachable: PLAUSIBLE-UNCHECKED, with what was tried.
