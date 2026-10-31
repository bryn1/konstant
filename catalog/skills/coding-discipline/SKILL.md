---
name: coding-discipline
description: How to write and change code so it stays small, honest and reviewable - the reuse ladder, file size limits (250/400/600) and splitting by concern, surgical edits, root-cause fixes, no dead code, entering an unfamiliar codebase or language, new-project layout. Load before writing or changing code, or when a file is growing.
---
# Coding discipline

## Reuse before you add (stop at the first rung that holds)

1. Does it need to exist at all? A speculative need is not a need: skip it and say so.
2. Is it already in this codebase? Reuse it (search by concern; it has another name).
3. Does the standard library do it? 4. A native platform feature? 5. An installed dependency?
   Never add a dependency for what a few lines can do.
6. Can it be one line? 7. Only now: the minimum code that works.

## Understand before you change

Locate where the behaviour lives; trace its callers and callees; name the invariants nearby (units,
time zones, ordering, locks, nullability); match the surrounding idiom. If you cannot state in two
sentences how it works now, read more. In an **unfamiliar language or repository**, take the build
and test commands from the repo (CI config, Makefile, manifest scripts), copy the nearest existing
test's style, and escalate when there is no discoverable build or test command, when the change
touches memory ownership or concurrency semantics you do not know, or after two compile-fix cycles
you cannot explain.

## Change surgically

- Surface ambiguity before the first edit: one sharp question, or the stated assumption.
- Every changed line traces to the task; do not improve adjacent code, comments or formatting.
- Remove what your change orphaned; report pre-existing dead code instead of deleting it in the same
  diff. Deliberate refactoring is its own task with its own tests.
- **Fix the root cause**: grep every caller of the function you touch; one guard in the shared
  function beats a guard in each caller.
- A deliberate shortcut carries a comment at the site naming its ceiling and the upgrade path. Never
  cut input validation at trust boundaries, data-loss handling, security or accessibility.

## File hygiene

One file, one concern. Source files target about **250** lines; over **400** split now or put
`reason: <why>` in the first five lines; **600** is the hard limit (tests up to 600). Generated,
vendored, migration, data and config files are exempt. Mixed concerns are the real problem: a file
mixing data access, business logic and presentation is wrong at 80 lines. Write it plainly first;
extract a unit when it is used twice, outgrows the target or mixes concerns, not before.

**Splitting**: name each concern in at most five words ("and" means two); extract the
weakest-coupled one first behind a clear interface; entry points only wire and start; prove each
resulting file answers fewer questions than the original (a split that only moves lines is not a
reduction). A `reason:` line schedules a split, it never absolves a mixed file.

## Dead code is capability that does not run

Before calling a build, port or refactor done, find modules nothing imports, functions nothing
calls and scripts nothing runs:

```
python3 .claude/skills/coding-discipline/scripts/dead_code.py <repo> --live <entry dirs> [--allow allow.txt]
```

Each finding is wired, deleted (own commit, tests green) or allow-listed with a reason. It is
name-based: calls by string, reflection or another language are invisible, which is what the allow
list is for.

## A new project

One directory, its own git repository at the root; one concern per file from the start; an isolated
environment (venv, node_modules), never global installs; a runnable entry point and a README that
answers WHAT it is, how to RUN it, how to TEST it, from day one; `docs/ARCHITECTURE.md` (skill
`workspace-layout`).

## Reporting

Compress, but never flip a meaning: keep `not`, `never`, `only`, `except`, exact numbers, units,
commands and paths; use full sentences for warnings and irreversible steps. Say which numbers were
measured and which inferred.
