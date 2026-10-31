---
name: test-design
description: Design tests that prove behaviour - test-first red/green/refactor, invariants and state transitions in both directions, the negative-case checklist, concurrency, property and boundary cases. Load when writing tests for new or changed code, or planning what a suite must cover.
---
# Test design

## Test first: red, green, refactor

1. **Red**: one minimal test for one behaviour, named for the behaviour. Run it and watch it fail
   for the right reason (the feature is missing, not a typo). A test that passes at once tests
   existing behaviour: fix the test.
2. **Green**: the simplest code that passes. Then the whole suite, output clean.
3. **Refactor** with the suite green: remove duplication, improve names. If a test breaks, undo.
4. Slice vertically: test1 -> impl1, test2 -> impl2. Writing all tests first and then all code makes
   brittle tests designed before anything was learned.

Code written before its test is deleted and rewritten test-first, not "kept as reference". Tests
written after pass immediately and prove nothing about what they would catch. Every few cycles,
re-scan the module for duplication and unclear intent and simplify old code too.

## What to test

**Invariants.** Write the rules the system promises as one-line statements with examples (valid
transitions, ranges, uniqueness, ownership, availability, calculations, lifecycle). Take them from
the project's contract; never invent rules it never promised. For each: the allowed case produces
the expected state; the forbidden case is rejected with a clear error **and leaves state
unchanged** (a rejected write that still mutated state is P0). Assert on domain state (row counts,
statuses, balances), never on "the request succeeded".

**The negative checklist**, with the expected outcome written before running:
invalid input (type, format, injection-shaped) · empty input · boundaries (0, -1, max, max+1,
exactly at the limit) · duplicates (same request twice) · missing resources (unknown id, deleted
parent) · stale state (old copy, expired token or lock) · invalid transitions (skipped or reversed
steps) · repeated operations (run it three times, expect one effect) · dependency failures
(timeout, partial response) · persistence failures (reason about them if you cannot simulate).
"It didn't crash" is not a pass: assert the error is the right one and the state is unchanged.

**Concurrency** where shared state is written: check-then-act races, duplicate writes, lost updates
(read-modify-write), non-atomic multi-step changes, two workers claiming one resource. Name the
serialisation mechanism (transaction, unique constraint, lock, single writer); none is the finding.
Test real concurrency (threads, processes, parallel requests), not a sequential loop, and assert
exactly one effect. "The database handles it" is a claim until you name the constraint.

**Properties** for logic with a wide input space: round-trip (decode(encode(x)) == x), idempotence
(f(f(x)) == f(x)), invariance under permutation, comparison against a simple reference model; let
the tool shrink failures to a minimal counterexample. Properties are written or approved by the
verifier, not by the author of the implementation they judge.

## Rules

- Real code, not mocks: mock only true externals, and never assert on the mock itself.
- One behaviour per test; a name with "and" is two tests.
- A feature with zero negative tests is UNVERIFIED regardless of its happy path.
- A bug fix starts with a failing test that reproduces it; that test stays as the regression test.
- Record each case: input | expected | observed | PASS/FAIL.
