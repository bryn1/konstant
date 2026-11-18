---
name: ssh-loop-prevention
description: Prevent agent hangs caused by looping SSH calls that return empty output or silent failure. Use when running SSH commands in a loop or when SSH calls return unexpectedly empty output.
---

# SSH loop prevention

## The problem

An agent running SSH commands in a loop can hang indefinitely or burn through tool calls when:
- The SSH command returns empty output (the remote script has no output, the command is wrong,
  or the host is unreachable but exits 0)
- The same failing SSH command is retried without any change to the inputs
- A `while read` loop uses SSH inside it — SSH reads from stdin and consumes the loop's input

## Rules

**Max 2 identical SSH calls.** If the same SSH command returns the same (empty or failing) output
twice in a row, stop. Do not retry a third time. The problem is not transient — it is structural.

**Decision tree on empty output:**
1. Was the remote command supposed to produce output? If yes, the command is wrong or the path
   does not exist. Verify the remote path before running the command.
2. Is the host reachable? Run `ssh -o BatchMode=yes -o ConnectTimeout=5 <host> true` to test
   connectivity separately from the actual command.
3. Did the command exit non-zero? Capture both stdout and stderr:
   `ssh host "cmd" 2>&1; echo "EXIT:$?"`
4. If you cannot determine why output is empty after two attempts, report BLOCKED — do not
   loop further.

**Never read SSH output in a `while read` loop over a list.** SSH consumes stdin, so it will
eat the remaining items in the list after the first SSH call. Use an index-based loop or pass
the list as an argument to the remote command instead.

**Hard stop on infinite loops.** If a loop has run more than 10 iterations without making
observable progress (a file written, a service state changed, a non-empty result), stop and
report the last N iterations of output. A loop that cannot make progress is a bug, not a
retry strategy.

## Diagnosis before retrying

Before retrying a failed SSH call, answer these:
- What exact command was run?
- What was the exact output (stdout + stderr + exit code)?
- Has the remote state changed since the last call?

If the state has not changed, another call will not change the result.
