---
name: test-quality
description: Judge whether tests and gates prove anything - could each stay green while the code is broken, mutation checks, planted reds, enumerate-don't-tally, CI that cannot swallow failures. Load when grading a suite, a CI pipeline or any check offered as evidence, or before trusting a new gate.
---
# Test quality: could it stay green while broken?

A green suite is a claim about the tests, not about the system.

## Per important test, answer

1. What behaviour does it actually exercise, and does it reach the real implementation or a mock?
2. What does the assertion guarantee, and what does it merely not check (truthiness, "not None",
   "no exception")?
3. What could break while it stays green? Is it vacuous (passes with the feature absent) or stale
   (tests a contract the code has moved past)?
4. Does it name the one claim it guards, and has anyone seen it fail?

Report each as EXERCISES / GUARANTEES / COULD-BREAK-WHILE-GREEN / verdict (meaningful, weak,
vacuous, stale). A vacuous test is worse than none: recommend deleting or rewriting it.

## Mutation check

Mutate the implementation and re-run: flip a comparison, swap two arguments, remove a guard, return
early on the error path. A suite that stays green through a mutation users would notice is
false-green for that behaviour. Where a tool exists, run it bounded to the changed packages
(Python `mutmut`, JavaScript/TypeScript Stryker, others per language) and carry the score into the
verdict; equivalent mutants and dead code are documented, not chased. No tool: the manual pass
above is the floor, and the report says `mutation: manual only`.

## False-green patterns

Testing the mock; asserting the mock's own return value; try/except swallowing the failure under
test; re-deriving the expected value with the implementation's own logic (a tautology); fixtures so
broad that any output matches; a test file that exists but is never collected (`no tests ran`).

## Every gate proves it can go red

For any check, selftest, monitor or CI step: run it once with a planted fault (invert the
condition, break the input, remove the node) and keep the red output beside the green one, and run
it once for real on the real target. A planted red proves the logic, not the environment (quoting,
paths, time zone, scheduler). A check that compares two values written from one variable can only
pass: read back what reached the world. Byte-identical green output across different inputs is the
tell of a check that does not look. A gate whose red cannot be produced is removed, not shipped.

## Enumerate, do not tally

Never hand-count "N of N passed". Discover what exists (glob the test files, ask the build system
for its declared tests) and assert that the same number ran; a suite on disk that did not run is a
FAIL.

## CI that fails honestly

Grep workflows and the scripts they call for exit-code swallows: `|| true`, `|| :`,
`continue-on-error`, `if: always()` on a step that judges, `set +e`, a pipe into `tee` without
`pipefail`, a multi-line step where only the last command counts. Each is guilty until justified;
the only legitimate always-run step uploads artifacts. A CI badge over a masked failure is a false
claim, automated.
