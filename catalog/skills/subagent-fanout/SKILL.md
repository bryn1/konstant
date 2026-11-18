---
name: subagent-fanout
description: How to design, brief and verify parallel subagent work - profile selection, dispatch brief format (context + task + DoD), pointer return convention, and how to verify results without trusting the agent's own summary. Use when dispatching work to parallel subagents.
---

# Subagent fanout — dispatching and verifying parallel work

Use this skill when you are breaking a typed task into parallel subagent runs. The goal is to
get useful, independently verifiable results without overwhelming context or spawning unnecessary
agents.

## When to fan out

Fan out when:
- Two or more pieces of work are genuinely independent (different files, different concerns)
- Each piece has a clear, checkable Definition of Done
- Running them in sequence would create an unnecessary bottleneck

Do NOT fan out when:
- The pieces depend on each other's output
- The overhead of briefing and verifying N agents exceeds the benefit
- The task is small enough to do inline

## Profile selection

Choose the profile by the kind of work, not by name affinity:
- **coder / builder** — writing or changing code
- **tester** — writing tests, running verification
- **reviewer / devil's advocate** — adversarial review of a plan or change
- **architect** — design, placement, structural decisions
- **researcher** — open-ended investigation, source gathering

One profile per subagent. Do not send one agent a mix of "build this AND test it AND review it".

## The dispatch brief format

Every subagent brief has three parts:

```
## Context
<What project this is. What has already been done. What the agent can depend on.
 Include exact file paths and relevant prior decisions.>

## Task
<Exactly what to build, change, or verify. No ambiguity. If there is a constraint,
 state it here. If there is a file to write to, name the exact path.>

## Definition of Done
<Specific, checkable criteria. Each line is one claim that can be independently verified.
 "The endpoint returns a 400 for a missing required field" not "the feature works".>
```

## The pointer return convention

Agents return pointers, not prose. The expected return is:
- The path to the artifact they produced
- A one-line outcome (PASS/FAIL/BLOCKED and why)
- Any critical blockers or new findings

**Do not trust a long summary.** A summary is a claim; the artifact is the evidence. Read the
artifact and verify the DoD lines yourself.

## Verifying results

For each dispatched agent:
1. Read the artifact they produced (do not read their summary of it)
2. Check each DoD line: is there evidence in the artifact for this claim?
3. A DoD line with no evidence is UNVERIFIED — do not mark the task done
4. If a line is FAIL or BLOCKED, name the specific gap before resuming

## Fan-out size

Keep the number of parallel agents small (2-4 for most tasks). More agents means more briefs to
write, more results to verify, and more coordination overhead. Prefer fewer, well-scoped agents
over many shallow ones.
