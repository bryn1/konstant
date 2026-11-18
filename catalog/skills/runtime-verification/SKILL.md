---
name: runtime-verification
description: Verify a build by running it and asserting on observable runtime behavior - not just exit codes, but the actual domain state the build was supposed to create. Use when a build claims to work and you need evidence beyond "tests pass".
---

# Runtime verification — verify what actually runs, not what the code says

A test suite that passes and an application that works are related but not the same thing. Runtime
verification proves that the actually-deployed artifact produces the right observable state.

## The chain

Work through these steps in order. Each step is evidence; a step you skip is a gap.

1. **Build / install.** The artifact builds from a clean checkout, or the package installs
   cleanly. Paste the build command and its last N lines of output.

2. **Start.** The application starts without errors. Paste the startup banner or health log line.

3. **Health check.** The application answers a health or readiness endpoint. Paste the response.
   An HTTP 200 with an empty body is NOT a passing health check — the response must contain
   something that proves the application is functional.

4. **Critical user journey.** Exercise one complete path through the system:
   - Make the real call (HTTP, DB write, file write, whatever the application does)
   - Inspect the resulting state (read the DB row, check the file, verify the response body)
   - The state must match what the code was supposed to produce

5. **Inspect state.** Read the actual stored state, not the return value of the write call. These
   can differ: a write that returns success may still store the wrong value.

## Evidence format

For each step:
```
STEP <n>: <name>
  ran: <exact command>
  output: <pasted output or "see attached">
  verdict: PASS | FAIL | BLOCKED
  note: <what this proves or why it failed>
```

## Common gaps

- **Testing the code, not the runtime.** Mocking a database and asserting the mock was called is
  not the same as asserting the database holds the right row.
- **Trusting the write call's return value.** Read back what was actually stored.
- **Skipping the startup banner.** An application that starts and immediately crashes may still
  exit 0 if the crash is in a background thread.
- **A health endpoint that always returns 200.** Verify that the health endpoint actually exercises
  the dependencies it claims to check (database connection, external service ping).
- **Testing on a different version than what is deployed.** The deployed artifact's commit SHA
  should match the tested commit.

## When to use this

Use runtime verification for every build that claims to be working — not as a replacement for the
test suite, but as the final check that the test suite's promises are kept by the actual running
artifact.
