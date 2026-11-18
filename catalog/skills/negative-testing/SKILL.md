---
name: negative-testing
description: Test what the code rejects, not just what it accepts. Checklist of negative test categories and the rule that a gate which cannot fail is not a gate. Use when designing tests or reviewing test coverage for missing negative cases.
---

# Negative testing — test what the code rejects

A test suite with only happy-path tests is incomplete. The code's rejection behavior is part of
its contract, and it is usually the part that breaks in production.

## The rule

**A gate that cannot fail is not a gate.** Before trusting any check, plant a fault and confirm
the check goes red. A test that stays green when the code is broken proves nothing.

## Negative test checklist

For each feature or function under test, check:

- **Invalid input** — inputs that violate the contract (wrong type, out of range, malformed
  structure). The system must reject them, not silently succeed or crash.
- **Empty and zero inputs** — empty string, empty list, zero, null/None. Many bugs live exactly
  here because the happy path never exercises them.
- **Boundary conditions** — one above and one below every stated limit. If a field accepts
  1-100, test 0, 1, 100, and 101.
- **Duplicate submissions** — the same request submitted twice. Does the system create two
  records, or is it idempotent?
- **Missing required fields** — omit each required field in turn and confirm a clear error.
- **State violations** — operations on a resource in the wrong state (calling close on an
  already-closed item, adding to a full container, transitioning from an invalid state).
- **Concurrency** — two simultaneous writes to the same resource. Does one win, or do both
  succeed silently with data loss?
- **Stale state** — a read followed by a write, where another writer changed the state between
  the two. Does the system detect the conflict?
- **Missing dependencies** — a resource that the function depends on does not exist (file not
  found, service unreachable, foreign key missing).

## The plant-a-fault requirement

For every check you add to your test suite or acceptance criteria:

1. Make the check pass on a correct implementation.
2. Break the implementation in the simplest possible way (comment out the guard, return a wrong
   value, skip the validation step).
3. Confirm the check goes **red** on the broken implementation.
4. Restore the implementation.

A check that cannot be made to go red is not checking anything.

## In reviews

When reviewing a test suite, for each piece of functionality ask: "can this test stay green while
the feature is broken?" If yes, the test has a gap. Name the specific break that would expose it.
