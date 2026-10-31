---
name: replace-a-running-system
description: Port, rewrite, migrate or retire a system that is live - inventory every side effect and consumer of the old one, port measured inputs, verify with a live shadow, cut over with an independent verifier, rehearse rollback, sweep old names to zero, retire with dates. Load whenever a change replaces something that runs today.
---
# Replace a running system

**Why**: a replacement can match the old system on 99 % of compared outputs, pass its gate, and
still drop everything the old process did besides that output (user controls, learners, statistics,
heartbeats, a device it drove). Parity proves agreement on what is compared, nothing else. Each step
below is an acceptance row, not advice.

## Standing rules

- The old system stays live until the new one is proven; never pause or edit it "temporarily".
  Shadow first (log-only, read-only) on the real target.
- The parity bar is the owner's; a cutover before it is met carries the owner's literal trade-off.
- Every new behaviour ships behind a kill switch that defaults to safe.
- Owner decisions as numbered options, recommendation and risk first.

## Plan: inventory before any port

1. **Side-effect inventory of the old system**: every file, table (read and write), environment
   variable, host, device write, timer, persisted state and user control it has. Each row ends
   PORTED (evidence), DROPPED (the owner's literal ruling) or NOT-YET.
2. **What the parity check excludes becomes rows**: each excluded case is behaviour nobody compared.
3. **Consumers of every old output**: who reads each file, table or endpoint (dashboards, monitors,
   other services, schedules)? Is each still fed after cutover?
4. **The name list**: every name the old system is known by (service, unit, container, script, log
   path, port, branch), for the final sweep.

## Build: port what runs, the way it ran

5. **Measured, not guessed**: every input the old system measured is read from the same source;
   never a value derived from the program's own output or a nearby proxy.
6. **No hard-coded time**: no literal UTC offset or DST rule; compute it from a time-zone database at
   the instant evaluated.
7. **Semantics proven physically**: a sensor or field label is a claim; prove it with a known-state
   reading. A learner that rejected every sample for weeks signals a fault, not calm.
8. **Every ported function has a live call site** (skill `coding-discipline`, dead code).

## Verify

9. Replay over history is the floor; a live shadow on the real target is the evidence (as-of bugs,
   values looked up at the wrong instant, only show live).
10. Every gate and monitor: a planted red and one real run on the real target.
11. Read back what reached the world (the device, the row), never two fields from one variable.
12. The cutover gate has an independent verifier; if none can run, the cutover is BLOCKED.

## Cut over and close

13. **Sweep the old names to zero live references** (schedules, units, health checks, configs,
    docs); re-point health checks at the new process. **Stopped is not retired**: remove it from
    the compose file or disable and mask the unit, and prove it with the tool (`docker compose
    config --services`, `systemctl is-enabled`).
14. **Provenance**: the running artifact reports its version or commit; deploy from a tag built in a
    clean clone, never from a working tree.
15. **Rollback rehearsed once**, or declared one-way by the owner in writing; date the rehearsal.
16. **Retirement list with dates**: every migration tool, schedule, check and flag, what guarantee
    it gave and what provides it now; nothing keeps comparing against a stopped system.
17. Close with evidence levels per row and de-stale the docs (skill `doc-hygiene`).
