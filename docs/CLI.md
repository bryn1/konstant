# konstant CLI reference

Generated from `konstant --help` by `python -m konstant.release clidoc --write`; do not edit by
hand (the test `test_cli_doc_parity` fails when this file and the parser disagree).

Every command takes the global flags `--as ROLE`, `--json` and `--config PATH`, before or after the
command. Run commands through `bin/konstant` inside the workspace (it sets `KONSTANT_HOME`).
Exit codes: 0 ok, 1 refused or failed, 2 usage error or not found; `task check`/`task run` add
3 UNMET, 4 BLOCKED, 5 check error; `verify` returns 0 PASS, 3 FAIL, 4 BLOCKED.

## `konstant`

```
usage: konstant [-h] [--as ROLE] [--json] [--config PATH] COMMAND ...

konstant: job board, task gate and verifier for coding agents.

positional arguments:
  COMMAND
    board        the job board server
    project      projects (each owns a root job)
    job          jobs on the board
    task         task gate, phase runner, DoD check
    verify       verify a completed job (probes + re-run)
    holdout      sealed holdout scenarios of a job (run only by verify)
    goal         level-5 goals: what the owner wants and its limits
    intake       turn a goal into jobs: planner, DoD review, filing, approval, scenario writer
                 (level 5)
    chat         the orchestrator chat as intake (the dsh plugin's seam)
    agents       generate and list the agent catalog surfaces
    dsh          start your dsh session (web, tui, headless) with the konstant gate plugin
    confinement  the confinement profile: what phases may see and do, per harness
    doctor       check that this workspace is ready (exit 0 when nothing FAILs)
    version      print the version

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant board`

```
usage: konstant board [-h] ACTION ...

positional arguments:
  ACTION
    init      create/migrate the DB, mint missing tokens
    serve     run the server in the foreground
    start     start the server in the background
    stop      stop the background server
    status    is the server up
    tokens    list roles/labels; rotate one (acts as owner unless --as says otherwise)
    backup    online backup of the board DB (default var/backups/board-<utc>.db)

options:
  -h, --help  show this help message and exit
```

## `konstant board init`

```
usage: konstant board init [-h] [--as ROLE] [--json] [--config PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant board serve`

```
usage: konstant board serve [-h] [--as ROLE] [--json] [--config PATH] [--host HOST] [--port PORT]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
  --host HOST
  --port PORT
```

## `konstant board start`

```
usage: konstant board start [-h] [--as ROLE] [--json] [--config PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant board stop`

```
usage: konstant board stop [-h] [--as ROLE] [--json] [--config PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant board status`

```
usage: konstant board status [-h] [--as ROLE] [--json] [--config PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant board tokens`

```
usage: konstant board tokens [-h] [--as ROLE] [--json] [--config PATH] [--rotate ROLE]
                             [--label LABEL]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
  --rotate ROLE  replace this role's token (owner only)
  --label LABEL  with --rotate: the factory identity of that role to replace (planner, dod-reviewer,
                 scenario: worker; factory: orchestrator); default the role's own token
```

## `konstant board backup`

```
usage: konstant board backup [-h] [--as ROLE] [--json] [--config PATH] [--to PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
  --to PATH      write the copy here instead
```

## `konstant project`

```
usage: konstant project [-h] ACTION ...

positional arguments:
  ACTION
    add       create a project and its root job
    list      list projects

options:
  -h, --help  show this help message and exit
```

## `konstant project add`

```
usage: konstant project add [-h] [--as ROLE] [--json] [--config PATH] [--name NAME] [--path PATH]
                            [--init-git]
                            slug

positional arguments:
  slug

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
  --name NAME
  --path PATH    project directory (default projects/<slug>)
  --init-git     git init the project directory
```

## `konstant project list`

```
usage: konstant project list [-h] [--as ROLE] [--json] [--config PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant job`

```
usage: konstant job [-h] ACTION ...

positional arguments:
  ACTION
    add       file a job (the brief must carry a DoD: line)
    list      list jobs
    show      show one job, untruncated
    search    prior-work lookup over titles and briefs
    claim     claim a queued or blocked job
    block     block a claimed job
    reopen    reopen a job
    cancel    cancel a job
    note      append a note or finding to the trail
    close     close with evidence (VERIFY_EXIT=0 required)
    review    close a review-type job into reviewed
    verdict   post a verifier verdict by hand (verifier/owner)
    move      move a job under another parent
    approve   approve a waiting job (owner)
    lint      check a brief's DoD before filing

options:
  -h, --help  show this help message and exit
```

## `konstant job add`

```
usage: konstant job add [-h] [--as ROLE] [--json] [--config PATH] --project PROJECT --brief FILE|-
                        [--type TYPE] [--parent PARENT] [--priority {0,1,2,3,4}] [--after ID]
                        [--approval] [--holdout-required]
                        title

positional arguments:
  title

options:
  -h, --help              show this help message and exit
  --as ROLE               act with this role's token, or a factory identity's (planner, dod-
                          reviewer, scenario, factory) (default [client] default_role)
  --json                  print JSON
  --config PATH           konstant.toml to use
  --project PROJECT
  --brief FILE|-
  --type TYPE             task type from catalog/types.yaml
  --parent PARENT         parent job id or display id (default: the project root)
  --priority {0,1,2,3,4}
  --after ID              claimable only once this job is verified
  --approval              file as waiting_approval
  --holdout-required      claimable only once its holdout scenarios are sealed
```

## `konstant job list`

```
usage: konstant job list [-h] [--as ROLE] [--json] [--config PATH] [--status STATUS] [--type TYPE]
                         [--project PROJECT] [--tree] [--self-attested] [--limit LIMIT]

options:
  -h, --help         show this help message and exit
  --as ROLE          act with this role's token, or a factory identity's (planner, dod-reviewer,
                     scenario, factory) (default [client] default_role)
  --json             print JSON
  --config PATH      konstant.toml to use
  --status STATUS    comma-separated states
  --type TYPE
  --project PROJECT
  --tree             indent by depth, include project roots
  --self-attested
  --limit LIMIT
```

## `konstant job show`

```
usage: konstant job show [-h] [--as ROLE] [--json] [--config PATH] [--trail] id

positional arguments:
  id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
  --trail
```

## `konstant job search`

```
usage: konstant job search [-h] [--as ROLE] [--json] [--config PATH] [--open] [--project PROJECT]
                           words [words ...]

positional arguments:
  words

options:
  -h, --help         show this help message and exit
  --as ROLE          act with this role's token, or a factory identity's (planner, dod-reviewer,
                     scenario, factory) (default [client] default_role)
  --json             print JSON
  --config PATH      konstant.toml to use
  --open             only jobs that are not finished
  --project PROJECT
```

## `konstant job claim`

```
usage: konstant job claim [-h] [--as ROLE] [--json] [--config PATH] id

positional arguments:
  id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant job block`

```
usage: konstant job block [-h] [--as ROLE] [--json] [--config PATH] id reason [reason ...]

positional arguments:
  id
  reason

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant job reopen`

```
usage: konstant job reopen [-h] [--as ROLE] [--json] [--config PATH] id reason [reason ...]

positional arguments:
  id
  reason

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant job cancel`

```
usage: konstant job cancel [-h] [--as ROLE] [--json] [--config PATH] id reason [reason ...]

positional arguments:
  id
  reason

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant job note`

```
usage: konstant job note [-h] [--as ROLE] [--json] [--config PATH] [--kind {note,finding}]
                         id text [text ...]

positional arguments:
  id
  text

options:
  -h, --help             show this help message and exit
  --as ROLE              act with this role's token, or a factory identity's (planner, dod-reviewer,
                         scenario, factory) (default [client] default_role)
  --json                 print JSON
  --config PATH          konstant.toml to use
  --kind {note,finding}
```

## `konstant job close`

```
usage: konstant job close [-h] [--as ROLE] [--json] [--config PATH] --evidence FILE id

positional arguments:
  id

options:
  -h, --help       show this help message and exit
  --as ROLE        act with this role's token, or a factory identity's (planner, dod-reviewer,
                   scenario, factory) (default [client] default_role)
  --json           print JSON
  --config PATH    konstant.toml to use
  --evidence FILE
```

## `konstant job review`

```
usage: konstant job review [-h] [--as ROLE] [--json] [--config PATH] --verdict FILE --done FILE id

positional arguments:
  id

options:
  -h, --help      show this help message and exit
  --as ROLE       act with this role's token, or a factory identity's (planner, dod-reviewer,
                  scenario, factory) (default [client] default_role)
  --json          print JSON
  --config PATH   konstant.toml to use
  --verdict FILE
  --done FILE
```

## `konstant job verdict`

```
usage: konstant job verdict [-h] [--as ROLE] [--json] [--config PATH]
                            id {PASS,FAIL,BLOCKED} [reason ...]

positional arguments:
  id
  {PASS,FAIL,BLOCKED}
  reason

options:
  -h, --help           show this help message and exit
  --as ROLE            act with this role's token, or a factory identity's (planner, dod-reviewer,
                       scenario, factory) (default [client] default_role)
  --json               print JSON
  --config PATH        konstant.toml to use
```

## `konstant job move`

```
usage: konstant job move [-h] [--as ROLE] [--json] [--config PATH] --parent PARENT [--reason REASON]
                         id

positional arguments:
  id

options:
  -h, --help       show this help message and exit
  --as ROLE        act with this role's token, or a factory identity's (planner, dod-reviewer,
                   scenario, factory) (default [client] default_role)
  --json           print JSON
  --config PATH    konstant.toml to use
  --parent PARENT
  --reason REASON
```

## `konstant job approve`

```
usage: konstant job approve [-h] [--as ROLE] [--json] [--config PATH] id

positional arguments:
  id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant job lint`

```
usage: konstant job lint [-h] [--as ROLE] [--json] [--config PATH] file

positional arguments:
  file

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant task`

```
usage: konstant task [-h] ACTION ...

positional arguments:
  ACTION
    classify  classify a task: small or a type, and why
    gate      print the gate block and write the run record
    run       run the phases and the DoD loop
    check     run the mechanical DoD check on a run
    close     close-out of an interactive run: MET -> close the job -> konstant verify
    judge     print the # JUDGED line for a run's deliverable state

options:
  -h, --help  show this help message and exit
```

## `konstant task classify`

```
usage: konstant task classify [-h] [--as ROLE] [--json] [--config PATH] text [text ...]

positional arguments:
  text           the task text, or - for stdin

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant task gate`

```
usage: konstant task gate [-h] [--as ROLE] [--json] [--config PATH] [--job JOB] [--project PROJECT]
                          [--type TYPE] [--out OUT] [--file-job] [--session SESSION] [--cwd CWD]
                          [--harness HARNESS]
                          text [text ...]

positional arguments:
  text               the task text, or - for stdin

options:
  -h, --help         show this help message and exit
  --as ROLE          act with this role's token, or a factory identity's (planner, dod-reviewer,
                     scenario, factory) (default [client] default_role)
  --json             print JSON
  --config PATH      konstant.toml to use
  --job JOB          the board job this run works on
  --project PROJECT  project slug (default: the job's project)
  --type TYPE        force the task type
  --out OUT          the OUT dir (default <project>/.audits/<stamp>-<slug>/out)
  --file-job         file and claim a job for a typed task that names none (the task text is the
                     brief: it needs a DoD section)
  --session SESSION  bind the job to this session id (var/sessions.json): its next typed task reuses
                     the open job
  --cwd CWD          the session's directory: the project whose path holds it when --project and the
                     job name none
  --harness HARNESS  the harness the orchestrating session runs in (where the gate block points for
                     agent profiles; default claude when configured)
```

## `konstant task run`

```
usage: konstant task run [-h] [--as ROLE] [--json] [--config PATH] [--job JOB] [--project PROJECT]
                         [--type TYPE] [--out OUT] [--file-job] [--session SESSION] [--cwd CWD]
                         [--harness HARNESS] [--max-cycles MAX_CYCLES] [--max-resumes MAX_RESUMES]
                         text [text ...]

positional arguments:
  text                       the task text, or - for stdin

options:
  -h, --help                 show this help message and exit
  --as ROLE                  act with this role's token, or a factory identity's (planner, dod-
                             reviewer, scenario, factory) (default [client] default_role)
  --json                     print JSON
  --config PATH              konstant.toml to use
  --job JOB                  the board job this run works on
  --project PROJECT          project slug (default: the job's project)
  --type TYPE                force the task type
  --out OUT                  the OUT dir (default <project>/.audits/<stamp>-<slug>/out)
  --file-job                 file and claim a job for a typed task that names none (the task text is
                             the brief: it needs a DoD section)
  --session SESSION          bind the job to this session id (var/sessions.json): its next typed
                             task reuses the open job
  --cwd CWD                  the session's directory: the project whose path holds it when --project
                             and the job name none
  --harness HARNESS          an adapter name (claude, codex, gemini, dsh) or an argv template for
                             every phase (default: [harness] in konstant.toml)
  --max-cycles MAX_CYCLES    back-edge cap (default [gate])
  --max-resumes MAX_RESUMES  DoD-loop resumes (default [gate])
```

## `konstant task check`

```
usage: konstant task check [-h] [--as ROLE] [--json] [--config PATH] [--offline] run

positional arguments:
  run            run dir (or its record.json, or a name under var/runs)

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
  --offline      no board reads (rule verified skipped)
```

## `konstant task close`

```
usage: konstant task close [-h] [--as ROLE] [--json] [--config PATH] run

positional arguments:
  run            run dir (or its record.json, or a name under var/runs)

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant task judge`

```
usage: konstant task judge [-h] [--as ROLE] [--json] [--config PATH] [--run RUN] [--out OUT]
                           [--project PROJECT] [--base BASE]

options:
  -h, --help         show this help message and exit
  --as ROLE          act with this role's token, or a factory identity's (planner, dod-reviewer,
                     scenario, factory) (default [client] default_role)
  --json             print JSON
  --config PATH      konstant.toml to use
  --run RUN          run dir (reads OUT, project and base from its record)
  --out OUT          OUT dir (without a run record)
  --project PROJECT  project dir (with --out)
  --base BASE        git base commit (with --out)
```

## `konstant verify`

```
usage: konstant verify [-h] [--as ROLE] [--json] [--config PATH] [--pending] [--dry-run]
                       [--no-rerun]
                       [id]

positional arguments:
  id             job id or display id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
  --pending      verify every completed_unverified job
  --dry-run      print the result, write nothing
  --no-rerun     skip the verify_cmd re-run
```

## `konstant holdout`

```
usage: konstant holdout [-h] VERB ...

positional arguments:
  VERB
    add       lint, control and seal scenario files (moves them into the store; owner)
    author    run the scenario writer for a job and seal its drafts (the scenario identity; exit 4
              refused twice)
    list      ids, kinds, commitments and states
    check     commitment + parse of each sealed file
    show      print one sealed scenario (never in a task)

options:
  -h, --help  show this help message and exit
```

## `konstant holdout add`

```
usage: konstant holdout add [-h] [--as ROLE] [--json] [--config PATH] --file FILE id

positional arguments:
  id             job id or display id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
  --file FILE    a scenario file outside the workspace (repeat for a set)
```

## `konstant holdout author`

```
usage: konstant holdout author [-h] [--as ROLE] [--json] [--config PATH] [--harness HARNESS] id

positional arguments:
  id                 job id or display id

options:
  -h, --help         show this help message and exit
  --as ROLE          act with this role's token, or a factory identity's (planner, dod-reviewer,
                     scenario, factory) (default [client] default_role)
  --json             print JSON
  --config PATH      konstant.toml to use
  --harness HARNESS  an adapter name for the scenario writer (default [holdout] writer_harness, else
                     [harness])
```

## `konstant holdout list`

```
usage: konstant holdout list [-h] [--as ROLE] [--json] [--config PATH] id

positional arguments:
  id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant holdout check`

```
usage: konstant holdout check [-h] [--as ROLE] [--json] [--config PATH] [--control] id

positional arguments:
  id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
  --control      also re-run the negative control on the project's HEAD
```

## `konstant holdout show`

```
usage: konstant holdout show [-h] [--as ROLE] [--json] [--config PATH] id hid

positional arguments:
  id
  hid            H<n>

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant goal`

```
usage: konstant goal [-h] VERB ...

positional arguments:
  VERB
    add       file a goal file (owner), or propose one from the owner's chat (--from-chat)
    list      goals with status, intake state, source
    show      one goal: spec, limits, its jobs
    pause     pause an active goal (owner)
    resume    resume a paused goal (owner)
    cancel    stop a goal for good (owner)

options:
  -h, --help  show this help message and exit
```

## `konstant goal add`

```
usage: konstant goal add [-h] [--as ROLE] [--json] [--config PATH] [--from-chat] [--session SESSION]
                         file

positional arguments:
  file               the goal TOML file, or - for stdin

options:
  -h, --help         show this help message and exit
  --as ROLE          act with this role's token, or a factory identity's (planner, dod-reviewer,
                     scenario, factory) (default [client] default_role)
  --json             print JSON
  --config PATH      konstant.toml to use
  --from-chat        a proposal from the orchestrator chat: filed when the owner's next message in
                     --session is a yes
  --session SESSION  the chat session id (default $KONSTANT_CHAT_SESSION)
```

## `konstant goal list`

```
usage: konstant goal list [-h] [--as ROLE] [--json] [--config PATH] [--status STATUS]

options:
  -h, --help       show this help message and exit
  --as ROLE        act with this role's token, or a factory identity's (planner, dod-reviewer,
                   scenario, factory) (default [client] default_role)
  --json           print JSON
  --config PATH    konstant.toml to use
  --status STATUS  filter: proposed,active,paused,done,stopped,withdrawn
```

## `konstant goal show`

```
usage: konstant goal show [-h] [--as ROLE] [--json] [--config PATH] id

positional arguments:
  id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant goal pause`

```
usage: konstant goal pause [-h] [--as ROLE] [--json] [--config PATH] id

positional arguments:
  id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant goal resume`

```
usage: konstant goal resume [-h] [--as ROLE] [--json] [--config PATH] id

positional arguments:
  id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant goal cancel`

```
usage: konstant goal cancel [-h] [--as ROLE] [--json] [--config PATH] id

positional arguments:
  id

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant intake`

```
usage: konstant intake [-h] [--as ROLE] [--json] [--config PATH] [--harness HARNESS] goal

positional arguments:
  goal               the goal id

options:
  -h, --help         show this help message and exit
  --as ROLE          act with this role's token, or a factory identity's (planner, dod-reviewer,
                     scenario, factory) (default [client] default_role)
  --json             print JSON
  --config PATH      konstant.toml to use
  --harness HARNESS  an adapter name or an argv template for the intake phases and the scenario
                     writer (default: [harness] / [holdout] writer_harness)
```

## `konstant chat`

```
usage: konstant chat [-h] VERB ...

positional arguments:
  VERB
    turn      one owner message: confirm/withdraw this session's goal proposal, new escalations, the
              intake block (JSON)

options:
  -h, --help  show this help message and exit
```

## `konstant chat turn`

```
usage: konstant chat turn [-h] [--as ROLE] [--json] [--config PATH] --session SESSION
                          text [text ...]

positional arguments:
  text               the owner's message, or - for stdin

options:
  -h, --help         show this help message and exit
  --as ROLE          act with this role's token, or a factory identity's (planner, dod-reviewer,
                     scenario, factory) (default [client] default_role)
  --json             print JSON
  --config PATH      konstant.toml to use
  --session SESSION  the chat session id
```

## `konstant agents`

```
usage: konstant agents [-h] VERB ...

positional arguments:
  VERB
    sync      render catalog/ into the surfaces of the configured harnesses (--check: report drift,
              write nothing)
    list      types, agents, skills, workflows

options:
  -h, --help  show this help message and exit
```

## `konstant agents sync`

```
usage: konstant agents sync [-h] [--as ROLE] [--json] [--config PATH] [--check]
                            [--harness {claude,codex,gemini,dsh,command}]

options:
  -h, --help                    show this help message and exit
  --as ROLE                     act with this role's token, or a factory identity's (planner, dod-
                                reviewer, scenario, factory) (default [client] default_role)
  --json                        print JSON
  --config PATH                 konstant.toml to use
  --check                       exit 1 naming every drifted file
  --harness {claude,codex,gemini,dsh,command}
                                only this configured harness's surfaces
```

## `konstant agents list`

```
usage: konstant agents list [-h] [--as ROLE] [--json] [--config PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant dsh`

```
usage: konstant dsh [-h] [--as ROLE] [--json] [--config PATH] [--project PROJECT] [--dry-run]
                    app ...

positional arguments:
  app                the dsh profile/app: web, tui or headless
  args               arguments for dsh after the patches

options:
  -h, --help         show this help message and exit
  --as ROLE          act with this role's token, or a factory identity's (planner, dod-reviewer,
                     scenario, factory) (default [client] default_role)
  --json             print JSON
  --config PATH      konstant.toml to use
  --project PROJECT  run the session in this project's directory
  --dry-run          print the argv, cwd and environment instead of starting dsh
```

## `konstant confinement`

```
usage: konstant confinement [-h] [--as ROLE] [--json] [--config PATH] SUBCOMMAND ...

positional arguments:
  SUBCOMMAND
    show         print the effective profile, options and how each configured harness enforces them

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant confinement show`

```
usage: konstant confinement show [-h] [--as ROLE] [--json] [--config PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant doctor`

```
usage: konstant doctor [-h] [--as ROLE] [--json] [--config PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```

## `konstant version`

```
usage: konstant version [-h] [--as ROLE] [--json] [--config PATH]

options:
  -h, --help     show this help message and exit
  --as ROLE      act with this role's token, or a factory identity's (planner, dod-reviewer,
                 scenario, factory) (default [client] default_role)
  --json         print JSON
  --config PATH  konstant.toml to use
```
