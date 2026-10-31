---
description: Run a test task - write and run an independent suite against a stated Definition of Done, then have it reviewed for gaps. Load when a task is [type:test] or a DoD asks for tests, coverage or a regression suite.
---
## Producer brief (the tester writes the suite and its verdict)

1. **Claims from the DoD**, written down first; each becomes one or more tests with an expected
   outcome stated before running.
2. **Design the cases** (skill `test-design`): invariants and state transitions, both directions of
   every rule, negative cases (invalid, empty, boundary, duplicate, missing, stale, concurrent).
3. **Real code, real boundaries**: import the module under test, hit the real HTTP server or CLI;
   mocks only where a dependency is truly external, and never as the thing asserted.
4. **Watch each test fail** against a deliberately broken implementation (mutation-style), then
   pass against the real one; a test you never saw fail is not trusted (skill `test-quality`).
5. **Enumerate, do not tally**: count the suites and tests that exist and assert that many ran.
6. Commit the suite in the project's test layout; write `TEST-verdict.md` with the run output.

## Review

The reviewer hunts for tests that would stay green through a real regression, missing negative
cases, DoD lines without a test, and CI or scripts that swallow exit codes (`|| true`,
`continue-on-error`, a pipe without `pipefail`).

## Exit

DONE.md maps each DoD line to its tests and their captured result; CLEANUP line; the check exits 0.
