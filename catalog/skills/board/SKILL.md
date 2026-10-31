---
name: board
description: How to record work on the konstant job board - search before filing, the job tree (project, feature with a DoD, task), writing a DoD the verifier can check (PROBE lines), claiming, notes, closing with an evidence file (VERIFY_CMD, VERIFY_EXIT, PROBE, COMMIT, DOCS), review closes, and what only the verifier may do. Load before filing, updating or closing a job.
---
# The job board

A task without a job does not exist. The board is the trail: the next session reads it instead of
asking you. Every command is `bin/konstant ...` (or the absolute path from a project directory).

## Search before you file

`bin/konstant job search "<words>" [--open]`. Extend an existing job rather than filing a duplicate;
cite it in your brief when you build on it.

## The tree (depth at most 2)

- depth 0: the **project** (`bin/konstant project add <slug>` creates it); never closes, no DoD.
- depth 1: a **feature** or deliverable; carries the DoD.
- depth 2: a **task** (`--parent <feature id>`), labelled `T1:`, `T2:` in order.

`job add` refuses depth 3. Order with `--after <id>` (a job cannot be claimed before its
predecessor is verified or reviewed). Priority is set at filing (0 highest).

## The brief and its DoD

```
bin/konstant job add "<title>" --project <slug> --type <type> --brief brief.md [--parent N]
```

The brief needs a `DoD:` (or `Acceptance:`) section: checkable lines, each naming an artifact path
or a command and its expected result, never "done when it looks done". A DoD line about live state
(a service running, a file present, a commit pushed) carries a probe the verifier can re-run:

```
DoD:
- `pytest -q` in projects/demo passes (12 tests)
- PROBE: test -f projects/demo/src/greet.py => ^ok$
- PROBE: git -C projects/demo log -1 --format=%s HEAD => greet
```

`bin/konstant job lint brief.md` names DoD rows no check can grade and PROBE lines the allowlist
would refuse; run it before filing. The acceptance text cannot be changed after filing.

## While working

`job claim <id>` to start · `job note <id> "<text>" [--kind finding]` appends to the trail ·
`job block <id> "<reason>"` when blocked (an honest block beats silence) · `job show <id> --json
--trail` reads the whole record.

## Closing with evidence

```
VERIFY_CMD: <the exact command you ran>
VERIFY_EXIT=0
<its output: summary lines, counts>
PROBE: <read-only command> => <regex>        (live state the verifier re-checks)
COMMIT=<sha>  BASE=<sha>                     (the commit that carries the change)
DOCS: <docs de-staled> | DOCS: n/a - <reason>
```

`bin/konstant job close <id> --evidence evidence.md`. The board refuses evidence without a real
`VERIFY_EXIT=0`, any non-zero exit line, a no-op check (`true`, a bare `echo`) and vacuous output
("ran 0 tests"). Review, docs, design and research jobs close with `job review <id> --verdict
<verdict file> --done <DONE.md>` instead, run by an identity that neither filed, claimed nor
closed the job (the owner or the verifier; the board refuses a self-review). `konstant verify`
passes a job only on a matched `PROBE:` from its DoD: file every build job with one.

## What you never do

Never post a verdict on a job you closed (the board refuses it), never set `verified` (only
`konstant verify` can, run by the verifier), never retype a token or put one in a brief, evidence
file or note.
