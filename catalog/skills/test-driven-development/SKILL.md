---
name: test-driven-development
description: RED-GREEN-REFACTOR cycle, the iron law of TDD, and when to apply the simple-design re-scan. Use when building a feature test-first or when establishing a TDD discipline on a codebase.
---

# Test-driven development — RED, GREEN, REFACTOR

TDD is a discipline for building reliable code with a minimal design. The cycle is short and
mechanical. The discipline is in following it.

## The iron law

**Write a failing test before writing any implementation code.** A test written after the
implementation proves what the implementation does, not what it should do.

There is exactly one exception: when you are exploring an unfamiliar API and need to understand
it before you can specify behavior. Exploration is not TDD; label it as such and throw away the
exploratory code before you start the TDD cycle for the real feature.

## The cycle

**RED.** Write a test for the next piece of behavior. Run it and confirm it fails (red). A test
that starts green either tests the wrong thing or the behavior already exists. If you cannot make
the test fail, your test is wrong.

**GREEN.** Write the simplest code that makes the test pass. Not the cleanest, not the most
general — the simplest. The goal of the green phase is a passing test, not good design.

**REFACTOR.** Clean the code. Remove duplication. Apply good names. The constraint is: all tests
still pass. Do not add new behavior in the refactor phase.

Repeat. Each cycle is one behavior increment.

## Cycle size

A cycle should take minutes, not hours. If a cycle takes longer than 10 minutes, the behavior
increment is too large. Split it.

## The simple-design re-scan (every 5th cycle)

Every 5th cycle, pause before moving to the next RED step and ask:
- Does the design have duplication that should be extracted?
- Is there a concept that lacks a name?
- Is there a class or function that holds more than one concern?
- Is the simplest design available, or did complexity accumulate?

This is not a refactoring sprint — it is a scan that may produce zero changes. Its purpose is to
prevent small accumulations from becoming a large refactoring debt.

## What TDD is not

- TDD is not "write tests after." Testing after is testing, not test-driven development.
- TDD is not a substitute for other kinds of testing. Integration tests, security tests, and
  load tests are not driven by TDD cycles.
- TDD does not guarantee a good design. It guides toward simple designs, but it does not replace
  architecture thinking.

## Starting TDD on an existing codebase

Pick the next feature or bug fix. Write a test for the specific behavior you are adding or fixing.
Do not try to test the existing code retroactively — that is a separate task with a separate
budget. Add tests for new and changed behavior; leave untouched code untouched.
