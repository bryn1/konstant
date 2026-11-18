---
name: security-audit-workflow
description: Six-phase security audit workflow adapted from established practices - threat model, static analysis, dependency scanning, manual review, secrets scan, and report. Use when conducting a full security audit of an application or codebase.
---

# Security audit workflow — six phases

Use this skill when conducting a full security audit. It is a workflow, not a checklist — work
through the phases in order, because each phase informs the next.

## Phase 0 — Scope and threat model

Before scanning anything:
- What is the attack surface? (HTTP endpoints, file uploads, authentication, payment, admin)
- Who are the likely attackers? (external users, authenticated users, insiders)
- What is the worst outcome? (data exposure, account takeover, financial loss, service disruption)
- What is out of scope? (say so explicitly)

A threat model that takes ten minutes is better than scanning without one.

## Phase 1 — Static analysis (SAST)

Run `semgrep --config auto <tree>` or a language-appropriate SAST tool. Focus on:
- Injection sinks (SQL, command, template)
- Taint flows from user input to dangerous sinks
- Authentication and authorization bypasses
- Use of deprecated/insecure APIs

Triage each finding: is the flagged sink reachable from untrusted input? Drop findings on
constants or unreachable paths; they are false positives.

## Phase 2 — Dependency scanning (SCA)

Run `pip-audit`, `npm audit`, `osv-scanner`, or `trivy` against the dependency lockfile. For each
high/critical vulnerability:
- Is the vulnerable code path actually used?
- Does a fixed version exist?
- What is the upgrade cost?

See `security-scan-triage` for the full scanner reference.

## Phase 3 — Secrets scan

Run `gitleaks detect --source <tree>` or `trufflehog filesystem <tree>`. Any committed credential
is CRITICAL — the fix is to rotate the credential AND remove it from history, not just the working
tree.

Report secrets by file:line and type. Never paste the value.

## Phase 4 — Manual review

After the automated scans, review manually for:
- **Authentication**: can a request bypass authentication? Is session management safe?
- **Authorization**: can a user access another user's data? Are admin paths protected?
- **Input validation**: is every user-controlled input validated before use?
- **Error handling**: do error messages leak internal paths, stack traces, or data?
- **Business logic**: see `business-logic-audit` for the method

For each finding, reproduce it in a sandbox before asserting it is exploitable.

## Phase 5 — Report

One ranked list, highest severity first:

```
[CRITICAL | HIGH | MEDIUM | LOW] <file>:<line> — <class>
  impact: <who is affected and how>
  verified: VERIFIED (<evidence>) | UNVERIFIED (reasoned only)
  fix: <specific change required>
```

Include a summary of what the automated scanners covered and what they cannot see (business logic,
authorization flows). Include what you tested and found nothing — that is evidence too.

## Scope constraint

A pool budget for a security audit: spend roughly half the time on automated scanning (phases 1-3)
and half on manual review (phase 4). Automated scanners are fast and reproducible; manual review
finds what they cannot.
