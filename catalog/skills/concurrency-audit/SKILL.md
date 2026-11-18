---
name: concurrency-audit
description: Audit concurrent code for races, deadlocks and atomicity violations. Use when reviewing code that runs multiple threads, processes or coroutines that share state.
---

# Concurrency audit

## Method

1. **Map shared mutable state.** List every variable, object, file, database row or external
   resource that two concurrent paths can both touch. This is the audit surface.

2. **For each shared resource, ask: "what happens if two tasks run this simultaneously?"**
   - Which path modifies it?
   - Which path reads it and acts on the result?
   - Is there a window between reading and writing where another task can intervene?

3. **Identify the serialization mechanism.** Is there a lock, a queue, a transaction, an atomic
   compare-and-swap, or nothing? If nothing: does the code assume single-threaded execution? Is
   that assumption documented and enforced?

4. **Test actual concurrency — not just the happy path.** A unit test that calls functions
   sequentially does not exercise concurrency. Reproduce the scenario that would trigger the race.

## Common findings

- **Check-then-act with no lock.** Read a value, decide to write, write — another writer can
  intervene between the read and the write. The fix is an atomic operation (compare-and-swap,
  SQL `UPDATE WHERE`, queue dequeue) rather than a lock around two separate calls.
- **Lock held too long.** A lock that spans I/O blocks all other waiters for the duration of the
  I/O. If the lock only guards the shared state, release it before the I/O.
- **Lock not held at all.** The code acquires a lock and then delegates work to a helper that also
  acquires the same lock — a re-entrant deadlock if the lock is not re-entrant.
- **Async task creating side effects without awaiting.** A fire-and-forget coroutine that writes
  to shared state has no ordering guarantee with the caller.
- **Stale state from cache or session.** A read that hits a cache which another writer updated —
  the reader acts on the old value.

## Findings format

```
[RACE | DEADLOCK | ATOMICITY | STALE] <location: file:line>
  shared resource: <what is shared>
  scenario: <two-line description of the concurrent scenario>
  current mechanism: <lock name, transaction level, or NONE>
  evidence: VERIFIED (<reproduction>) | UNVERIFIED (reasoned only)
  fix: <atomic operation, lock scope change, queue, or redesign>
```
