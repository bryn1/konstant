---
name: workspace-convention
description: Where a project's files live - project home structure, audit run directories, scratch dirs, file placement checklist, and versioned-truth doctrine for truth files. Use before writing any project file - a brief, build, audit or fix.
---

# Put every deliverable where the team can find it, the same way every time

If a file's location cannot be predicted from its project name and kind, the next reader — human
or agent — has to search for it, and a searcher who cannot find it treats the work as not done.

## The project layout

```
<project-root>/
  docs/ARCHITECTURE.md              the architecture statement — one canonical home; kept
                                    true by the architect after every change that touches
                                    modules, entry points, ports, or data stores
  .audits/<YYYYMMDD-HHMM>-<slug>/   every audit / verify / fix run: findings, verdict files
                                    (# VERDICT: ...), CYCLES.md, DONE.md
  .tmp/                             scratch; never a deliverable
```

**Never again**: `<project>-audit-<date>/` sibling directories beside the project. One project,
one directory. Runs go into `.audits/` inside the project.

## Durable evidence

A run's durable outputs — verdict files, evidence summaries, gate scripts — should be committed
so they survive a re-clone. Scratch output, caches, and raw transcripts stay host-local.

Minimum committable artifacts per run:
- Root-level `.md` files (verdict, evidence, DONE, CYCLES)
- Gate/verify scripts (`*.sh`, `*.py` in `out/`)
- Summary logs

Exclude from version control: nested scratch clones, build caches, raw transcripts, full frame
sets, engine outputs.

## Naming and placement rules

**Project directory name** is the thing being worked on, not the person doing the work and not the
task kind. `matapp`, not `alice-matapp` or `Matapp`. Lowercase-kebab.

**Before creating a new project directory**, check for a near-miss name: `ls | grep -i <project>`.
A second directory for a project that already has one is exactly the defect this layout prevents.

**Audit run directory** (`<YYYYMMDD-HHMM>-<slug>`) uses UTC timestamp at the time the run
STARTS. `<slug>` is a short dash-joined description of this run (`fix-hygiene`, `arch-verify`,
`security-pass`) — one run, one timestamped dir, never reused across runs.

## Before you write a file — checklist

1. Does `<project>/` already exist (right casing, no persona prefix)? If not, create it at the
   canonical path.
2. Is this a source file? → goes in the project tree.
3. Is this an architecture statement or update? → `docs/ARCHITECTURE.md`, the ONE canonical home.
4. Is this a run's output (findings, verdicts, cycle logs)? → a fresh
   `.audits/<YYYYMMDD-HHMM>-<slug>/` dir.
5. Is this scratch? → `.tmp/`.
6. `mkdir -p` the target directory first, every time.
7. If this artifact is cited by a tracked doc, it must be committable so it survives a re-clone.

## Versioned-truth doctrine

Editing a truth file (a SKILL.md, SOUL.md, AGENTS.md, ARCHITECTURE.md, or a registry file) or
changing a host configuration produces a **new current version**. The superseded version is
archived and labeled, never deleted.

- **Archive + label**: move the superseded copy to `docs/archive/<name>-<date>/` and add
  `SUPERSEDED <date>: DO NOT USE — live version: <path>` as the first line.
- **Never delete.** Archive = move + label.
- **Never overwrite another agent's file.** To supersede your own earlier output, write a new
  dated file in a fresh `.audits/<run>/` dir.

## Two hard rules

- **Append-only for other agents' files.** Never delete or overwrite work another agent produced.
- **No secrets in the project directory.** Credentials, tokens, keys, and `.env` contents stay
  out of the project tree.
