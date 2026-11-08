---
name: fan-out
description: Hand a phase to a subagent and get a verifiable result back - pick the agent by task type, write a self-contained brief (what, skills, read, write, DoD, constraints), keep children as leaves, parallel only for independent work, wait for every child, then verify the artifact yourself. Load before spawning any subagent.
---
# Fan-out: brief a child, get a pointer, verify the artifact

## The mechanism

- A child knows **nothing** of your conversation: everything it needs travels in its brief. Spawn
  the agent named for the phase (`.claude/agents/<agent>.md`); its profile carries its role,
  contract and doctrine, so the brief carries only this task.
- Children are **leaves**: every brief says it never spawns agents or sub-sessions.
- Children may run in the background; **wait for each result** and never end your turn with a child
  still running (its result would be lost). Never sleep-poll in a shell.
- **One concern per child, one writer per file**: two children never write the same file. Give
  each child the exact path to work in.
- **Parallel** only for independent concerns (no shared file, no dependency): the phases the gate
  marks parallel, or the parts of a `fanout`/`max` task. **Never more children at once than the
  cap** the intake card prints (`[harness] max_concurrency` // `max_parallel`): children beyond
  the endpoint's slots evict each other's prompt cache and all of them finish later. **Sequential** when a child needs another's artifact: never spawn the tester
  before the build is committed or the reviewer before the plan exists.
- A child that is clearly off task or over a reasonable time budget is stopped and re-briefed.

## The brief

```
WHAT:        the one concern, in one self-contained paragraph
SKILLS:      the skills to load first (always workspace-layout; the type's skills)
READ:        exact input paths, or "none"
WRITE:       the exact artifact path (OUT, the project tree, the verdict file name)
DoD:         an observable end state: an absolute path that exists with the right content, or a
             command and its expected exit code or count ("pytest -q exits 0, 12 passed"). A build
             child's DoD is a commit; a verifier's DoD ends with its verdict line.
JUDGE:       for a verifying phase, the judge command to run last
CONSTRAINTS: commit format, "no TODOs", "no second mechanism beside an existing one", scope
JOB:         the board job id (the child does not write to the board; you do)
```

A build child's DoD carries a size bound: one concern per commit; a commit over about 30 files or
1,500 lines with no test file is rejected and split.

## Decomposition is your job

Split by step, not only by module: "write X, register it, sync it and verify it" is four children,
each naming the exact command or mechanism to use; a combined brief invites the child to reinvent
the mechanism. When the split itself is the hard part, that is a design task (architect) first.

## When the child returns

It returns a pointer (path plus one-line outcome, or BLOCKED plus the failing command). Then you:
read the artifact, not the summary; run the check that proves the DoD; record the evidence on the
board. On BLOCKED: re-brief with the corrected instruction, re-spawn, or escalate. Never do a
blocked child's work inline to save time, and never grade a child's work by its own description.
