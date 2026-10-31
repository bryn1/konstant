---
name: security-review
description: Reason about what scanners cannot see - trace untrusted input to SQL, file, URL, deserialization and model sinks; authorization order and ownership checks; prompt injection and agent-instruction surfaces; secrets, permissions and local-to-public bridges - via a six-phase audit with independent confirmation. Load for a security review, audit or threat model.
---
# Security review

Scanners catch known patterns (skill `security-scan-triage`); the bugs that hurt live in the flow.
Rank every finding CRITICAL / HIGH / MEDIUM / LOW with `file:line`, impact and fix.

## The audit shape

1. **Recon**: architecture, trust boundaries, entry points, data stores, prior findings; keep a
   coverage list of what was examined (a strong finding in one area says nothing about another).
2. **Hunt** by unit from that list, scanners first, then the reasoning below.
3. **Confirm**: each candidate goes to a different agent whose only job is to disprove it; the
   finder never confirms its own finding.
4. **Record** three outcomes: confirmed (full source trace and a bounded observed result),
   needs-validation (the exact unresolved fact, no severity), rejected (disproved, kept on record).
5. **Re-verify** the final records' claims after any fix, and re-run the fix's own checks over the
   whole deliverable (half-applied fixes recur).
6. **Report** derived from the confirmed records, never written first.

## Application flow

- **Trace each untrusted input** (parameters, headers, uploads, documents, chat messages) to every
  sink: SQL (parameterised end to end, or injection), filesystem (normalise, then check against an
  allow-listed root: path traversal), outbound URL (allow-list destinations, block internal ranges:
  SSRF), deserialisation (safe loaders only; never `pickle` or unsafe YAML on untrusted bytes).
- **Authorization before work**: authenticate -> authorize with an ownership check on the specific
  object -> validate -> rate-limit -> act. Work done before the check is an oracle or an
  exhaustion vector. A role alone is not an ownership check.
- **Data**: minimal personal data, retention limits, redaction in logs, no internals in errors,
  responses return no more than needed; export and deletion paths where personal data is kept.

## Model and agent surfaces

- Model input is untrusted: can a message or ingested document steer the model to leak other users'
  data, grade falsely, emit unsafe content or reveal its instructions? Model output that drives an
  action is a sink to validate. Only reviewed content should reach a retrieval corpus that serves
  users.
- Instruction files agents read (prompts, skills, rules, memory) are an execution surface: an edit
  that tells an agent to widen permissions, disable a guard, exfiltrate or publish is CRITICAL
  whoever wrote it. Diff every change to such files against its prior version.

## Host and credential hygiene

- Privilege grants are minimal (one user, one command, no wildcards, no environment passthrough to
  a shell) and validated before install (skill `infra-hardening`).
- Secrets live in owner-only files referenced by path; a secret in a world-readable or committed
  file is CRITICAL, and anything pushed to a remote counts as exposed.
- "It is all local" bounds who picks something up, not what it unlocks. Enumerate local-to-public
  bridges (automatic pushes, sync jobs, backups) and contain the writer, not only the reader.

## Boundary

Read-only: fixes are recommendations. Reproduce CRITICAL and HIGH in a sandbox only; never against
a live system or real users' data. Escalate a live-data or live-credential CRITICAL immediately.
State what you did not cover.
