---
name: adr
description: Write an architecture decision record only for decisions with two or more viable options that are costly to reverse - one template, sequential numbering, the owner as the only accept authority, superseded records kept. Load when a design or plan forces a decision someone will later ask "why did we choose this?" about.
---
# Architecture decision records

## When to write one

Both must hold: **two or more viable options** exist, and the choice is **costly to reverse**
(rework, redeploy, data migration, operational change). A single sensible path (a security patch, a
compliance fix) needs no record. An ADR on a routine edit is noise that teaches everyone to ignore
ADRs. Test: will someone come back in six months and wonder why?

## Where and how numbered

`docs/adr/adr-NNNN-<slug>.md` in the project, indexed in `docs/adr/README.md` (number, title, status,
date, board job). Take the highest number + 1, zero-padded; never reuse or renumber; write the file
and its index row in the same commit, so two authors cannot claim one number unnoticed.

## Template (one format, never a second)

```
# ADR-NNNN: <the decision, phrased as a question or a choice>

- Status: DRAFT | PROPOSED | ACCEPTED <date> | REJECTED | SUPERSEDED by ADR-MMMM
- Job: <board job id>   Date: <drafted> / <decided>
- Verified at source: <the files, commands or measurements the facts below were read from>

## The question
What was asked, in the asker's words, and what forced a decision now.

## Options considered
| Option | What it buys | What it costs | Killer fact (file:line, measurement) |

## Decision
One paragraph: the chosen option and its boundary.

## Why: load-bearing facts
Numbered; each cites the artifact it was read from.

## Consequences
What changes, what is rejected and why, the cost accepted, when to revisit.

## Rule of thumb (optional)
The one line a future reader can apply without re-reading the record.
```

Implementation detail belongs in the board job, not the record.

## Lifecycle

DRAFT -> PROPOSED (author done) -> ACCEPTED or REJECTED, decided by the owner only; an agent never
marks its own ADR accepted. A changed decision gets a new ADR that supersedes the old; the old one
stays, its status line updated to `SUPERSEDED by ADR-MMMM`, never deleted or rewritten.
