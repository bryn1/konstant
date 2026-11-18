---
name: test-quality-audit
description: Eight questions to ask of every test, and the mutation testing pass that proves the suite can go red. Use when grading test quality or deciding whether a test suite is trustworthy evidence.
---

# Test quality audit — does the test suite actually prove anything?

A green test suite is not evidence that the code works. It is evidence that the code satisfies
the tests. This skill is the method for checking whether the tests themselves are trustworthy.

## The eight questions

For every test (or representative sample from the suite):

1. **Does this test name one claim?** A test named `test_user_creation` may be testing five
   things. Each should be a separate test.

2. **Can this test stay green while the code is broken?** If you comment out the feature,
   does the test fail? If not, the test is testing the wrong thing.

3. **Does this test reach the real implementation?** A test that mocks the function under test
   tests the mock, not the function.

4. **Does this test assert meaningful state?** A test that only asserts "no exception was raised"
   proves that the code ran, not that it produced a correct result.

5. **Is the negative side tested?** For every behavior the code rejects, is there a test that
   confirms the rejection?

6. **Are the assertions specific?** `assert result` is weaker than `assert result == expected`.
   A vague assertion can pass on a wide range of wrong outputs.

7. **Is the test independent?** Does this test depend on the execution order of other tests, or
   on shared mutable state left by another test?

8. **Is the test deterministic?** Would this test produce the same result on a re-run, without
   race conditions or time dependencies?

## The mutation testing pass

After answering the eight questions, run a mutation test. The principle: if you change one line of
the implementation in a simple way (flip a comparison operator, change a return value, skip an
if-branch), the test suite should go red.

Manual mutation steps:
1. Pick a behavior in the implementation.
2. Change one line (flip `>` to `>=`, return a wrong value, comment out a guard).
3. Run the tests.
4. If they stay green: the behavior is not tested. This is a gap.
5. Restore the change.

Automated mutation testing tools (mutmut for Python, stryker for JavaScript) systematize this —
they apply dozens of mutations and report what percentage are caught. A mutation score above 80%
is a reasonable bar for a production test suite; below 60% is a sign of significant gaps.

## Findings format

```
[TEST-GAP | MOCK-TESTING-NOTHING | WEAK-ASSERTION | ORDER-DEPENDENT | NON-DETERMINISTIC]
  test: <test name>
  question: <which of the 8 questions this fails>
  evidence: <specific observation>
  fix: <what a good test for this behavior would assert>
```
