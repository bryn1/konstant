---
name: poc-vs-production
description: Classify a reported issue as an actual bug, a design limitation, an intentional PoC shortcut, a production-hardening item, or an optional improvement. Use when triaging findings on a proof-of-concept or early-stage build.
---

# PoC vs production — classifying findings on an early build

When reviewing a proof-of-concept, prototype, or early build, findings need to be classified
before they are acted on. Not every gap is a bug. Not every limitation needs to be fixed now.

## The five classifications

**1. Actual bug** — the code does not do what it claims to do, or what the task required.
Symptoms: wrong output, exception on a valid input, a promise in the README that is not kept.
Action: fix it before claiming done.

**2. Design limitation** — the current design cannot support this without a rethink.
Example: a caching layer that cannot be invalidated, or a data model that cannot hold the new
requirements.
Action: document the limitation; decide whether to redesign now or defer.

**3. Intentional PoC limitation** — a known shortcut that is acceptable for a PoC but not
for production. Examples: in-memory storage that does not persist, hardcoded credentials, no
error handling.
Action: document it explicitly as a known PoC limitation. Do NOT present it as a bug.

**4. Production-hardening item** — the PoC works but needs strengthening before it can carry
real traffic or real data: proper logging, retries, authentication, rate limiting, monitoring.
Action: file it as a follow-up task; do not block the PoC on it.

**5. Optional improvement** — the PoC works, the limitation is real, but it is not a blocker
for the stated goal. Address it only if there is budget and it is worth the trade-off.
Action: document it and move on.

## How to apply this

For each finding, state:
- Which class it falls into, and why
- Whether it blocks the current goal (PoC acceptance, demo, handoff)
- Whether it is documented so the next reader does not rediscover it

A PoC with two actual bugs and six intentional limitations is not "broken" — it is a PoC with
two bugs to fix and six documented trade-offs.
