---
name: security-review-reasoning
description: Manual security reasoning for two layers - application security (authn, authz, injection, data handling) and infrastructure security (host access, secrets, deployment). Use after running deterministic scanners when manual reasoning is needed.
---

# Security review reasoning — after the scanners

This skill covers manual security reasoning for two layers. Run the deterministic scanners
(`security-scan-triage`) first — they are faster and more reproducible. This skill covers what
scanners cannot see.

## Layer 1 — Application security

Work through each category. For each finding, record: the location, the scenario, the evidence,
and the fix.

**Authentication**
- Can a request reach a protected resource without credentials?
- Is session management correct (tokens expire, are invalidated on logout, are not predictable)?
- Are password resets safe (no enumeration, tokens are single-use and time-limited)?

**Authorization**
- Can a user read or modify another user's data by guessing IDs?
- Are there admin or internal routes that lack authorization checks?
- Does the authorization check happen on every code path, or only on the "normal" path?

**Injection**
- Are all user-controlled values parameterized before use in SQL, shell, or template contexts?
- Are file paths sanitized? Can a user traverse outside the intended directory?
- Are deserialization inputs trusted? (pickle, YAML with `Loader=`, XML external entities)

**Data handling**
- Is sensitive data (passwords, tokens, PII) stored with appropriate protection?
- Are responses consistent whether a resource exists or not (avoid enumeration)?
- Are error messages stripped of internal paths and stack traces before reaching the user?

**Upload and file handling**
- Are uploaded file types validated (content-type AND magic bytes, not just extension)?
- Are uploaded files stored outside the web root?
- Is there a size limit on uploads?

## Layer 2 — Infrastructure security

**Host access**
- Are SSH keys the only authentication method? Is password auth disabled?
- Are sudo grants minimal — specific commands, not `NOPASSWD: ALL`?
- Is the firewall policy deny-by-default, and does it survive a reboot?

**Secrets**
- Are secrets stored as root-owned files, referenced by path, never hardcoded?
- Does the secret appear in any log, job record, or version-controlled file?
- Is the same secret duplicated? (duplication means multiple rotation points)

**Deployment**
- Does the service restart after a reboot (`systemctl is-enabled`)?
- Are service units using `DynamicUser`, `NoNewPrivileges`, or other hardening flags?
- Is there a monitored health check that alerts when the service is down?

## Findings format

```
[CRITICAL | HIGH | MEDIUM | LOW] <category> — <location>
  scenario: <two-line description of the attack>
  evidence: VERIFIED (<command and output>) | UNVERIFIED (reasoned only)
  fix: <specific change>
```

Reproduce every CRITICAL and HIGH finding in a local/sandbox environment before asserting it is
exploitable. Never test against a production system.
