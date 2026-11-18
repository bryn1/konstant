---
name: adr-authoring
description: When to write an Architecture Decision Record (two or more viable options AND costly to reverse), the canonical template, number allocation to avoid collisions, the status lifecycle, and evidence discipline. Use for decision-class work on a project or infrastructure.
---

# ADR authoring — write Architecture Decision Records consistently

Write ADRs the same way across the project. One shared format, one allocation mechanism. No
second template.

## 0. When to write an ADR

A task is **decision-class** when BOTH conditions hold:

1. **Two or more viable options exist.** If there is only one sensible path (a security patch, a
   compliance fix, a one-way door), an ADR is not needed — just do it.
2. **Costly to reverse.** Reverting would require significant rework, re-deployment, data
   migration, or operational change.

An ADR on a routine edit is noise that trains people to ignore ADRs. When in doubt, ask: *will
anyone come back in six months and wonder why we chose this?* If no, skip the ADR.

## 1. The canonical template

Every ADR follows this structure:

1. Header: `# ADR-NNNN: <decision title, as a question or a choice>`
2. Metadata bullets: **Status** / **Date** (drafted / decided) / **Verified at source** (which
   artifacts ground the facts — never docs-only)
3. `## The question` — what problem forced a decision now
4. `## Options considered` — a table: Option | What it buys | What it costs | Killer fact
5. `## Decision` — one paragraph; the chosen option and its boundary
6. `## Why — load-bearing facts` — numbered; each fact cites the literal artifact (file:line,
   probe output)
7. `## Consequences` — what changes, what is rejected and why, cost accepted, revisit-when
8. `## Rule of thumb` (optional) — the one-liner a future reader can apply without re-reading

Do not add sections like "Acceptance Criteria" or "Implementation Notes" — implementation detail
belongs in the task record, not the decision record.

## 2. Number allocation (avoiding collisions)

Two authors must not allocate the same ADR number. Protocol:

1. Read the index (typically `docs/adr/README.md`) to find the highest existing number.
2. Allocate the next available number (highest + 1, zero-padded: `ADR-0007`). Never reused.
3. Claim it immediately — write the file with its number before finishing other work.
4. Update the index with the new entry in the same commit.

If you do not have write access to the shared repo when writing the ADR, write a draft with a
placeholder number and hand it off to whoever has write access to allocate the final number.

## 3. Status lifecycle

`DRAFT` → `PROPOSED` (author done, decision-maker not yet asked) → `ACCEPTED <date>` or
`REJECTED` → later `AMENDED <date>` (details corrected, the decision itself unchanged) or
`SUPERSEDED-BY-NNNN` (the decision reversed or its premise gone).

- **The decision-maker is the only accept authority** — never self-accept.
- **The draft must precede the decision.** An ADR written after the fact is a rationalisation.
- **`AMENDED` = amend in place** when only details are stale but the decision still binds.
- **`SUPERSEDED` = write a new ADR** when the decision is reversed. Never delete the old ADR.

## 4. Evidence discipline

Label every factual claim:
- **VERIFIED** — observed this session (file read, command output, probe)
- **UNVERIFIED** — inferred but not directly checked
- **ASSUMED** — reasonable but unconfirmed; state the assumption
- **BLOCKED** — could not verify; state what blocked it

Cite `file:line` or probe output. Never invent evidence.

## 5. What makes ADRs actually get written

An instruction in a document does not cause ADRs to be written. What causes them:

1. **Filing the task with ADR acceptance.** The task record names an ADR artifact as a required
   output. A task that cannot be closed without producing the ADR is structurally forced.
2. **A subsequent task that reads the ADR as an input.** If the next step's brief requires the
   ADR path, a missing ADR structurally blocks the next step.

What does NOT cause ADRs to be written: this skill on its own; soul rules; a git pre-commit hook
(the author may not be committing from a repo checkout). The honest limit: recognizing that work
is decision-class happens at task-filing time, and that recognition requires judgment.
