---
name: truth-audit
description: Eight-step method to classify claims in a report as verified, overstated, unverified or wrong - and to identify the instrument behind each measurement. Use when a report or decision rests on claims that need to be checked before being trusted.
---

# Truth audit — classifying claims before trusting them

Use this skill when a report, finding, or decision rests on claims you need to verify before
acting on them. It applies to your own outputs as well as others'.

## The eight steps

1. **List the decision-changing claims.** Which claims, if wrong, would change what you do? Start
   there. Do not audit every sentence — focus on the ones that matter.

2. **Classify each claim by type:**
   - **Factual** — a thing that is or is not true about the world (a service is running, a file
     exists, a value is 42)
   - **Measured** — a number produced by running an instrument (a count, a rate, a percentage)
   - **Inferred** — a conclusion drawn from other claims (the system is broken because X and Y)
   - **Asserted** — stated without evidence (trust me, it works)

3. **For factual claims: name the instrument.** Which command, query, or observation would show
   this claim to be true or false? If you cannot name one, the claim is UNVERIFIABLE.

4. **For measured claims: name the parse.** What was counted, filtered, and skipped? A count
   without its filter is not repeatable. If two reasonable methods produce different numbers,
   report the range and name the methods.

5. **Run the instrument.** Do not accept a claim as VERIFIED until you have run the instrument
   yourself. A claim the author verified is AUTHOR-VERIFIED until you re-run it.

6. **Classify the result:**
   - `VERIFIED` — instrument run, result matches claim
   - `OVERSTATED` — instrument run, result is weaker/narrower than the claim
   - `WRONG` — instrument run, result contradicts the claim
   - `UNVERIFIED` — instrument not run; plausibility only
   - `UNVERIFIABLE` — no instrument can check this claim

7. **Identify the instrument behind the claim.** A claim that rests on a measurement should name
   the measurement. A claim that cites a source should cite the exact line, not the document.

8. **State the residual uncertainty.** What would have to be true for the VERIFIED claims to be
   wrong? Name the assumptions you did not check.

## The instrument boundary

A measurement carries the parse that made it. When a count comes from a tool or a query:
- Name the filter (what was included, what was excluded)
- State the word/token boundary if matching text
- Note whether the instrument is deterministic (the same input always produces the same output)

A count without a named filter is not a count — it is a range bounded by two interpretations.

## Anti-patterns

- **Citing a document instead of a line.** "The docs say X" means nothing without a line number.
- **Trusting a previous agent's verification.** Re-run the instrument yourself.
- **Treating absence of contradiction as confirmation.** No one contradicted the claim, so it
  must be right — this is the quietest path to acting on wrong information.
