---
name: reuse-first
description: Check prior work before building anything - the board, the project's docs and code, then the outside world - reuse what exists, gate genuinely novel pieces on research, and record what you learned so the next search finds it. Load at the start of any task or sub-step that might already be solved.
---
# Reuse first: check, reuse, and only then research

```
STEP 0    check prior work -> reuse it                       (always; cheap)
STEP 0.5  nothing found AND genuinely novel -> research it   (a gate before building)
STORE     the distilled finding where the project keeps knowledge
```

## STEP 0: check prior work (every genuine unit of work)

Search by **concern**, not by name; the existing thing is almost always called something else.

- The board: `konstant job search "<words>"`. A verified job may already own this: cite it, extend
  it. A hit on one incidental word is a weak lead, not a duplicate.
- The project: its docs (`docs/ARCHITECTURE.md`, decision records, the README) and the code
  (`grep -rn`) for a module, script, helper or config that does the job.
- Installed dependencies and the standard library before anything new.

If prior art exists, reuse it: extend the module, cite the job. A hit is a lead to verify, not a
fact. Starting from scratch when prior art exists is the waste this step prevents.

## STEP 0.5: research gate (only when both hold)

1. STEP 0 found nothing, **and**
2. the piece is genuinely novel to you (an unfamiliar library, API, format or pattern), not a rename,
   a wiring step or a config you understand.

Then do not build the novel piece until you have checked whether the world already solved it:
official docs, the library's own examples, maintained packages (skill `citation-discipline` for
how to read sources honestly). A project-scale question is its own research task. One research
question at a time per task, batched: the gate is not a licence to fan out.

## STORE: make it cheaper next time

Record the distilled, durable finding (the lesson or pattern, not the search dump) where the
project keeps knowledge: its docs, a decision record, or the board job's evidence. Stable facts
only ("library X does Y via Z"), never a volatile count presented as permanent; English; no
secrets.

## When not to load

You are executing a plan whose steps were already researched; the whole task is familiar; the work
is read-only analysis that builds nothing.
