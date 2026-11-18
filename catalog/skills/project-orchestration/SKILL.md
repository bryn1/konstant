---
name: project-orchestration
description: The orchestration loop for advancing a multi-step project - check state, pick the next unblocked task, brief and dispatch a worker, verify the result, update state, repeat. Use when you are the orchestrator of a project with multiple parallel or sequential tasks.
---

# Project orchestration — advancing a multi-step project

Use this skill when you are the person who keeps a project moving, not the person doing the
individual tasks. Your job is to know what is next, brief the right worker, verify the result, and
advance the board.

## The loop

Repeat until done:

1. **Read the board.** What is in progress, what is blocked, what is ready? Do not rely on memory;
   read the actual state.

2. **Pick the next task.** Choose based on dependencies (what must be done before this), risk
   (what is most likely to surface a blocker), and parallelism (what can run concurrently).

3. **Brief the worker.** A brief has three parts:
   - **Context**: what project this is, what has already been done, what the worker can depend on
   - **Task**: exactly what to build or verify — no ambiguity
   - **Definition of Done**: the specific, checkable criteria the worker must satisfy before
     reporting done

4. **Dispatch and wait.** Send the brief. Do not guess at the result; wait for it.

5. **Verify the result against the DoD.** Not "did they say they're done" — does the artifact
   satisfy each DoD line? If any line is unverified, it is not done.

6. **Update state.** Mark the task done, update the project record, note any new blockers or
   discoveries.

7. **Identify new work.** A completed task often surfaces follow-up tasks. File them before
   moving on.

## What makes a good Definition of Done

A DoD line is good when:
- It is **checkable** — someone other than the author can verify it without asking the author
- It is **specific** — not "the feature works" but "the endpoint returns a 400 for a missing
  required field"
- It is **bounded** — it covers one claim, not a category

A DoD that cannot be checked is a wish list.

## Orchestrator rules

- **Never assume a task is done because someone said so.** Read the artifact or run the check.
- **Never merge incomplete work.** A task that satisfies 4 of 5 DoD lines is not done; it is 80%
  done with one outstanding issue.
- **A blocked task needs a decision, not more waiting.** When a task is blocked, name exactly what
  unblocks it and who must decide.
- **Parallel work needs explicit coordination.** If two tasks can share a file or a resource,
  say so in both briefs and assign an owner for the conflict resolution.
