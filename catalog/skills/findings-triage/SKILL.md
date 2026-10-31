---
name: findings-triage
description: Classify a finding before fixing it - actual bug, design limitation, intentional prototype limitation, hardening opportunity, optional improvement - and rank it P0-P4. Load when a review or test produces findings, or before "fixing" behaviour that might be deliberate.
---
# Findings triage: is it a bug or a choice?

Turning an intentional simplification into production architecture without being asked is a scope
violation and often breaks the design. Classify first.

## Classes

- **Bug**: behaviour contradicts the project's own stated contract or intent.
- **Design limitation**: the design cannot do X; changing it is a design decision, not a fix.
- **Intentional prototype limitation**: a deliberate simplification for the project's stage
  (hard-coded values, single user, no auth, in-memory state), documented or clearly implied.
- **Hardening opportunity**: a real gap that matters once the project goes to production (auth,
  migrations, monitoring, rate limits).
- **Optional improvement**: no correctness impact.

## How to classify

1. What does the project say it is (README, brief, stated stage, owner statements)?
2. Does the behaviour contradict that contract? Bug.
3. Consistent but limited? Design or prototype limitation: was it chosen deliberately?
4. Would fixing it change the architecture? Hardening, needs a decision.
5. Unsure between bug and deliberate limitation: report it as UNRESOLVED and ask; never pick the
   reading that lets you write code.

## Rank

P0 correctness, data loss or security · P1 important functional bug · P2 reliability or
maintainability · P3 production hardening · P4 optional. A currently improbable race that corrupts
data is still P1.

## Rules

Record the class and rank next to every finding; an unclassified finding is incomplete. Never fix a
deliberate limitation without an explicit request. Limitations that will bite later go on the risk
list, not the fix list. Do not fix unrelated problems because they exist: file them as jobs.
