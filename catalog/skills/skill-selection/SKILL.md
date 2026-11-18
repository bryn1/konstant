---
name: skill-selection
description: Default skill pairings by task type - which skills to load for coding, testing, review, research, infrastructure and security tasks. Use when starting a task and deciding which skills to load.
---

# Skill selection — default pairings by task type

Skills are loaded on demand. This skill is a quick reference for which skills to load for common
task types. It is not exhaustive — load additional skills when the task description calls for them.

## By task type

**Coding / building**
- `coding-discipline` — always, for any code change
- `architecture-review` — when the change involves a design decision
- `negative-testing` — when writing tests or verifying a build
- `failure-taxonomy` — when claiming a build is done

**Testing / verification**
- `negative-testing` — always
- `runtime-verification` — when verifying a deployed or running artifact
- `test-quality-audit` — when grading an existing test suite
- `test-driven-development` — when writing tests before the implementation

**Review / adversarial pass**
- `architecture-review` — for design or approach review
- `failure-taxonomy` — always check against known failure classes
- `citation-discipline` — when the work includes measurements or external claims
- `truth-audit` — when claims need to be traced to artifacts

**Research**
- `citation-discipline` — always, for any external source
- `reuse-research-gate` — before building something that might already exist
- `spike` — when validating feasibility before committing to a full build

**Infrastructure / host changes**
- `infra-hardening` — always
- `replace-a-running-system` — when replacing something live
- `runtime-verification` — after the change

**Security**
- `security-scan-triage` — run deterministic scanners first
- `security-review-reasoning` — for manual reasoning after the scanners
- `security-audit-workflow` — for a full security audit pass
- `infra-hardening` — for host/infrastructure security

**Documentation / close-out**
- `doc-hygiene` — always, to de-stale what your change made wrong
- `citation-discipline` — when the docs include measurements or external sources

## Pairing principle

Skills are not exclusive. A code review may load `architecture-review`, `failure-taxonomy`, and
`negative-testing` simultaneously. Load the ones that match the task; skip the ones that do not.
