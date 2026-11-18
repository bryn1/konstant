---
name: business-logic-audit
description: Audit the business-logic layer of an application - invariants, state transitions, boundary conditions and cross-cutting rules. Use when checking whether the core rules of the system are enforced correctly, not just whether the code runs.
---

# Business-logic audit

Purpose: verify that the application's core business rules are **actually enforced** in the code,
not just described in a README.

## Method

1. **Enumerate invariants.** What must always be true? (e.g. "an order total cannot be negative",
   "a user cannot exceed their quota"). These come from domain knowledge, the README, and the data
   model — not from reading the implementation first.

2. **Map state transitions.** What states can a record be in? What moves it between states? Draw
   the happy path, then ask: what happens on each failure path? Is there a state the system can
   enter that it cannot exit?

3. **Test valid, invalid and boundary inputs — per invariant.** For each invariant: what inputs
   satisfy it, which violate it, and which sit at the boundary? Each class needs a test.

4. **Verify the enforcement site.** Where in the code is this rule enforced? Is it enforced once,
   centrally — or does it rely on every caller remembering to check? A rule enforced only by
   convention is one refactor from being violated.

5. **Check the actual state.** Run the system and inspect real rows/records. A rule that holds
   in tests but not in production data is a finding.

## Findings format

```
[INVARIANT] <name>
  claimed: <what the docs/README promise>
  enforced at: <file:line> | NOT ENFORCED
  test coverage: <what case is tested> | NONE
  actual state: VERIFIED | VIOLATED (<evidence>)
```

## What this is not

This skill is for business rules: the domain constraints that define correct behavior. It does not
cover authentication, authorization, SQL injection, or infrastructure security — those belong to
the security skills. It does not replace running the full test suite.
