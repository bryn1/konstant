---
name: spike
description: Run a throwaway feasibility experiment before committing to a build - split the idea into 2-5 risky questions, research just enough, build the smallest observable prototype, and end each with a VALIDATED, PARTIAL or INVALIDATED verdict. Load when an approach is uncertain, two options need a head-to-head, or "is this even possible?" cannot be answered from docs.
---
# Spike: feel out an idea before the real build

Not for questions the docs or the code answer (research instead), not for production work (plan and
build instead), not for ideas already validated.

## Method: decompose, research, build, verdict

1. **Decompose** into 2-5 independent feasibility questions, each phrased Given/When/Then with an
   observable outcome ("Given a 50-page PDF, when parsed with library X, then tables come out as
   rows in under 5 s"). Order by risk: the question most likely to kill the idea runs first.
   Comparison spikes share a number with letter suffixes (002a, 002b).
2. **Agree the list** with whoever asked before building, when there is more than one spike.
3. **Research per spike, briefly**: two or three sentences on what it tests and why; the competing
   approaches (maintained? license? fit?); pick one and say why. Skip for pure logic.
4. **Build** one directory per spike (`spikes/NNN-name/` with a README and the code), standalone and
   hard-coded: no build systems, containers or config layers unless the question is about them.
   Prefer an output someone can interact with: a CLI that prints observable results, a minimal
   page, one endpoint, or a test with recognisable assertions. Test edge cases; never declare "it
   works" after one happy-path run.
5. **Verdict** at the end of each README:

   ```
   ## Verdict: VALIDATED | PARTIAL | INVALIDATED
   What worked / What did not / Surprises / Recommendation for the real build
   ```

   PARTIAL names its constraints; INVALIDATED is a successful spike.

## Comparisons

Build the variants back to back, then a head-to-head table on the dimensions that matter (quality,
setup cost, speed on realistic input, edge cases) and a named winner with the condition under which
the loser would win.

## Rules

Spike code is thrown away: if it takes days to "clean up for production", it was not a spike. The
real build starts from the verdict and its recommendation, test-first. Record the verdict where the
project keeps knowledge so nobody repeats the experiment.
