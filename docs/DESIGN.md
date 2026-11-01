# konstant — design (v0.1.0, pre-release; level-5 waves L5-1 and L5-2 landed)

konstant is a self-contained workspace for running coding agents with discipline: a local job
board (**board**), a deterministic **task gate** that turns a task into phases run by one agent
profile per task type, a mechanical **Definition-of-Done (DoD) check + loop**, a built-in
**verifier** that re-checks closed work by read-only probes, and a catalog of **agents, skills and
workflows** generated into the surfaces an agent harness reads (Claude Code, Codex, Gemini CLI,
DeepSeek Harness or any CLI agent; docs/HARNESSES.md).

Level 5 (docs/LEVEL5.md) lands wave by wave; this document describes what exists. Wave L5-1 added
sealed holdout scenarios (§7.1): black-box acceptance checks a producing phase cannot read, run
only by the verifier. Wave L5-2 added factory mode (§7.2): every phase of a holdout job confined
in konstant's jail on any harness, per-identity tokens the board compares, and job clones with a
read-only target.

References of the form F-nn and G-nn name findings of the two independent security reviews of
v0.1; docs/CONCEPTS.md "Security reviews" summarises them, and each has a test under `tests/review/`.

The release is a tarball. `./install.sh` inside the unpacked folder turns that folder into the
workspace. Nothing is written outside it; uninstall = delete the folder.

## 1. Principles (the "why" the code enforces)

1. **A claim is not a result.** Work is done when an artifact proves it, checked by something other
   than the author. The board refuses a close without an executed check (`VERIFY_EXIT=0`), and only
   the verifier role can mark a job `verified`.
2. **A check that cannot fail is not a check.** Vacuous evidence ("ran 0 tests") is refused; every
   gate rule ships with a planted-bad test that must go red.
3. **One source per fact.** Task types, their agents, phases, verdict files and skills live in ONE
   file (`catalog/types.yaml`); the gate, the DoD check, the board and the generator all read it.
4. **Replace, do not add beside.** A new mechanism names what it replaces and removes it.
5. **Deterministic where possible.** Classification, the DoD check and verification make no model
   call. Models do the work; code decides whether the work is done.
6. **Least reach.** Everything lives in the install folder; the board binds to loopback; probes are
   read-only and allowlisted; no command is ever run through a shell by konstant itself except a
   recorded verify command the user's own agent already ran.

Non-goals for v0.1: multi-host deployment, a hosted service, any LLM-as-judge, Windows outside WSL,
PyPI publication, notifications/chat integrations.

## 2. Layout

### 2.1 Repository (= release tarball contents)

```
konstant-0.1.0/
  install.sh                 # turns this folder into a workspace (idempotent)
  get.sh                     # the one-line installer (§10.1); also a release asset
  bin/konstant               # CLI wrapper (tracked; install.sh rewrites the same text, 0755)
  pyproject.toml             # package "konstant", python >= 3.10
  README.md  LICENSE  CHANGELOG.md  SECURITY.md  CONTRIBUTING.md
  src/konstant/
    __init__.py  __main__.py   # __version__ = "0.1.0"
    config.py                  # konstant.toml load + defaults; workspace root resolution
    client.py                  # stdlib HTTP client (urllib) used by every CLI verb
    catalog.py                 # load + validate catalog/types.yaml, agents, skills, workflows
    cli/                       # argparse front end: main, board, project, job, task (+ task_run,
                               # task_session), verify, holdout, agents, dsh, doctor
    board/
      app.py                   # FastAPI app factory, static read-only UI
      api/                     # deps (auth deps, serialisation), projects, jobs (file/read),
                               # lifecycle (claim..move, dod-review), verify (verdict), trail,
                               # tokens routes,
                               # holdouts (seal + list commitments; the verdict's holdout hooks)
      db.py  migrate.py  migrations/0001_init.sql  0002_holdouts.sql  0003_workdir.sql
      dod.py                   # DoD extraction from a brief (required) + DoD row lint (warnings)
      policy.py                # role sets + switches from konstant.toml, fail-closed defaults
      transitions.py           # the job state machine (one table)
      tree.py                  # depth <= 2, display ids, move validation
      evidence.py              # evidence contract, vacuity lexicon, negative control
      auth.py  redact.py
      static/                  # index.html, board.js, board.css (read-only view)
    gate/
      classify.py  render.py  record.py      # task -> type -> gate block -> run record
      runner.py  harness.py  loop.py         # phase runner, harness process + per-type set, DoD loop
      reaper.py                              # nothing a phase starts outlives it (subreaper)
      check.py                               # rule engine, exit codes
      rules/  common.py verdicts.py (verdicts + phases) judged.py done.py tests.py
              lastmile.py hygiene.py exercise.py verified.py authorship.py cleanup.py
    verify/   probe.py  shapes.py  native.py  procenv.py  rerun.py  verifier.py
              holdout.py                     # materialise the pinned commit, jailed no-net runs (§7.1)
    holdout/  lint.py  store.py  leak.py     # scenario format + lint, seal/check, leak scan (§7.1)
    factory/  clone.py  doctor.py            # job clones, factory doctor rows (§7.2)
    harnesses/ base.py claude.py codex.py gemini.py dsh.py command.py   # adapters (§9)
               dsh_session.py dsh_gate/{index.ts,build.mjs,konstant-gate.mjs} # dsh session plugin (§6.6)
    jail.py                                  # bubblewrap jail for agent-written code
    machinery.py                             # ONE list: paths no phase writes + credential homes (§9)
    agents/   generate.py                    # catalog -> harness surfaces
    release/  build.py  scan.py  clidoc.py   # maintainer tooling (`python -m konstant.release`)
  catalog/
    types.yaml               # THE source: types, agents, phases, verdict files, skills, keywords
    agents/<agent>.md        # 9 task agents + orchestrator.md
    doctrine/base.md         # shared principles every profile inherits
    doctrine/contracts/{build,verdict,doc}.md
    skills/<name>/SKILL.md   # 26 skills
    workflows/<type>.md      # 9 workflows
    templates/CLAUDE.md.tmpl  AGENTS.md.tmpl  agent.md.tmpl  skill.md.tmpl
              operate.md.tmpl  # the "how to operate konstant" table both top docs include
  release/patterns.toml      # generic public-safety patterns (IPs, emails, token shapes, paths)
  tests/  unit, board, cli, gate, verify, catalog, release, holdout, factory, fixtures/,
          e2e/{fresh_install.sh, one_line.sh, dsh_session.sh}
  docs/   DESIGN.md  QUICKSTART.md  CLI.md  CONCEPTS.md  HARNESSES.md  DSH.md
  .github/workflows/ci.yml   # CI (export-ignore)
  .gitattributes  .gitignore
```

### 2.2 Workspace after `./install.sh` (git-ignored additions)

```
<folder>/
  bin/konstant               # (re)written: KONSTANT_HOME=<folder> exec .venv/bin/python -m konstant "$@"
  konstant.toml              # local config (port, harness command, policy)
  .venv/
  var/board.db               # SQLite (WAL)
  var/secrets/<role>.token   # 0600, dir 0700; plaintext only here, sha256 only in the DB
  var/runs/<stamp>-<slug>/   # task-run records: record.json, phases/*.json, logs, events
  var/holdout/<job>/H<n>.scenario   # the SEALED holdout store (0700 dirs, 0400 files; §7.1):
                             # masked in every jail, read-denied by every adapter
  var/logs/  var/backups/  var/board.pid
  projects/<slug>/           # default home of user projects (git repos)
  .claude/agents/<agent>.md  .claude/skills/<skill>/SKILL.md  .claude/settings.json
  CLAUDE.md  AGENTS.md       # generated; regenerated by `konstant agents sync`
  .agents/skills/  .dsh/konstant.patch.yml  .gemini/{settings.json,konstant-policy.toml}
  .dsh/{konstant-session.patch.yml,konstant-gate.mjs,agents/<agent>.md}   # dsh session (§6.6)
                             # generated only for the configured harnesses (§8, §9)
  var/harness/<name>/        # relocated harness homes (dsh, gemini): no user-level config
                             # (dsh: home/ for phases, session/ for `konstant dsh`)
  var/sessions.json          # session id -> bound job (§6.6)   var/logs/konstant-gate.log
```

A harness started anywhere inside the folder (Claude Code walks up to the nearest `CLAUDE.md` and
`.claude/`) sees the agents, skills and rules. Projects added with `--path` outside the folder are
supported, but the generated surfaces only apply inside it (stated in QUICKSTART).

## 3. Components

```
 user / harness (Claude Code, any CLI agent)
        |  bin/konstant ...
        v
  CLI ---- HTTP (loopback, bearer token) ----> board (FastAPI + SQLite)
   |  task gate/run/check                         ^
   |     | renders phases from catalog/types.yaml |  close / review / verdict
   |     v                                        |
   |  harness adapter -> one harness run per phase|
   |  DoD check (files in OUT + git) -> loop      |
   |  verify: probes + rerun ---------------------+ (verifier role)
   |  agents sync: catalog -> .claude/, CLAUDE.md, AGENTS.md
```

## 4. Board data model

### 4.1 Tables (`migrations/0001_init.sql`; `schema_meta.version` drives `migrate.py`)

| table | columns (essential) | notes |
|---|---|---|
| `schema_meta` | `version` | one row |
| `projects` | `id, slug UNIQUE, name, path, root_job_id, status(active/archived), created_at` | `path` = project dir (default `projects/<slug>`) |
| `jobs` | `id, project_id, parent_id, type, title, brief, acceptance, status, priority, requested_by, assignee, after_id, approval_required, verify_round, closed_by, evidence_json, result_summary, created_at, updated_at, holdout_required` | `acceptance` immutable after insert; `type` validated against `catalog/types.yaml` (root jobs have type `project`); `holdout_required` (v2): claimable only with sealed holdouts; `workdir`, `workdir_base` (v3): the job clone and the target commit it starts from, set by the first claim of a holdout job, then immutable |
| `trail` | `id, job_id, ts, actor, role, kind, body, payload_json` | append-only; kinds: `note status evidence verdict finding move approval review`, and since v2 the level-5 kinds `dod-review holdout ship rollback escalation budget` (`holdout` and, since L5-2, `dod-review` are written) |
| `verifications` | `id, job_id, round, actor, started_at, finished_at, verdict(PASS/FAIL/BLOCKED), probes_json, rerun_json, holdout_json` | the verifier's ledger; `holdout_json` (v2) holds scenario ids, pass/fail, timings, the commit and the commitment digest, never a command or an output |
| `holdouts` (v2) | `id, job_id, hid, kind(proof/regression), sha256, author_label, sealed_at, trail_id, generation, state(sealed/burned/retired)` | a COMMITMENT per scenario (sha256 of the file; its canary is the salt), never content; no delete; commitment columns immutable; `state` only moves forward from `sealed` (DB triggers) |
| `runs` | `id, job_id, run_dir, type, started_at, finished_at, result(MET/UNMET/BLOCKED/ERROR)` | links task runs to jobs; written by `task run --job` through `POST /api/jobs/{ref}/runs`; `GET /api/jobs/{ref}` returns the job's `verifications` and `runs` |
| `tokens` | `id, role, label, sha256 UNIQUE, active, created_at` | `label` is the actor identity (e.g. `orchestrator`, `verifier`; the factory identities `planner`, `dod-reviewer`, `scenario`, `factory`: §5) |

Hierarchy: depth 0 = project root (auto-created by
`project add`, never closes, no DoD), depth 1 = feature (carries the DoD), depth 2 = task. Depth > 2
is refused. `display_id` is the full path `"<root>.<seq>.<seq>"`, derived at read time; the old form
resolves too. A job without `--parent` is filed under its project root.

Text fields pass through `redact.py` (token-shaped strings, private keys, `KEY=value` secrets) before
insert. `evidence_json` stores `verify_cmd`, `verify_exit` (int), `verify_output` (first 4,000
bytes), optional `control_cmd`/`control_exit`, `commit`, `base`, `self_attested`.

### 4.2 Job states and transitions (`board/transitions.py`, one table)

States: `queued, waiting_approval, claimed, blocked, completed_unverified, verified, reviewed, cancelled`.
Terminal: `verified`, `reviewed`. `cancelled` is closed but reopenable.

| from | verb | to | allowed roles | guard |
|---|---|---|---|---|
| (new) | `add` | `queued` or `waiting_approval` | owner, orchestrator, worker | acceptance non-empty with a DoD line; type known; depth ≤ 2; `approval_required` → `waiting_approval` |
| `waiting_approval` | `approve` | `queued` | owner | — |
| `queued` | `claim` | `claimed` | orchestrator, worker | `after_id`, if set, is `verified`/`reviewed`; a `holdout_required` job has at least `[holdout] min_per_job` sealed holdouts (409 `no holdout sealed`; §7.1) |
| `claimed` | `block` | `blocked` | owner, orchestrator, worker | reason required |
| `blocked` | `claim` | `claimed` | orchestrator, worker | — |
| `claimed` | `close` | `completed_unverified` | requester or assignee, owner | evidence contract (§4.3) |
| `claimed`, `completed_unverified` | `review` | `reviewed` | review roles | type in `review_types` (review, docs, design, research); actor ≠ requester, assignee and closer (nobody reviews their own job; F-03); a reviewer verdict `SHIP` and a DONE.md given |
| `completed_unverified` | `verdict PASS` | `verified` | verifier, owner | actor ≠ `closed_by`; a holdout job's PASS carries the verifier's holdout result: every sealed holdout passed, the set's commitment digest, no LEAK (else 409) |
| `completed_unverified` | `verdict FAIL` | `queued` (round+1) or `blocked` at `max_rounds` | verifier, owner | findings appended to the trail |
| `completed_unverified` | `verdict BLOCKED` | unchanged | verifier, owner | reason appended |
| `completed_unverified`, `blocked`, `cancelled` | `reopen` | `queued` | reopen roles | reason required |
| any non-terminal | `cancel` | `cancelled` | owner, orchestrator | reason required |
| any | `move` | (unchanged) | owner, orchestrator | target depth valid; a `move` trail row |

An illegal transition answers 409 naming the current state and the legal verbs; a role refusal
answers 403 naming the required roles. Order: the role is checked first (403), then the state
(409), then the verb's own guard (403 ownership/closer, 409 dependency/type, 422 missing input).
A project root (depth 0) refuses every verb with 409. There is no verb that writes `verified` except a verifier
verdict, and `verified` cannot be left.

### 4.3 Evidence contract on `close`

1. `verify_cmd` non-empty and not a no-op (`true`, `:`, `exit 0`, a bare `echo`/`printf`: it
   cannot fail; F-02), `verify_exit` an integer equal to 0, `verify_output` non-empty.
2. **Vacuity:** output that says it measured nothing ("ran 0 tests", "collected 0 items", "no tests
   found") is refused unless it also reports a non-zero count of subjects; "0 failed"/"0 errors" pass.
3. **Negative control (opt-in):** if `control_cmd` is given it must have exited non-zero and not 126/127.
4. Warnings, never refusals: no `DOCS:` line; every `PROBE:` line points only at the evidence file
   itself (self-attested; recorded in `evidence_json.self_attested`).
Modes per check: `off | warn | strict` in `[board.policy]` (default strict for 1-3).
For a job with holdouts the runner's close evidence carries `COMMIT=<HEAD of the project>` and
`BASE=<the run's base>` (and DONE.md lines can never set either): the holdouts run on exactly that
commit (§7.1).
The CLI builds the payload from the evidence file: `VERIFY_CMD:` (or `=`), every `VERIFY_EXIT=<n>`
line (any non-zero one wins: never close on red), `CONTROL_CMD:`/`CONTROL_EXIT=`, `COMMIT=`,
`BASE=`, `PROBE:` lines, the first `DOCS:` line, and the first 4,000 bytes as `verify_output`. The
board enforces the contract; the client only reads the file.

## 5. Auth and roles

Roles: `owner`, `orchestrator`, `worker`, `verifier`, `viewer`. `konstant board init` mints one random
token per role (`secrets.token_urlsafe(32)`) into `var/secrets/<role>.token` (0600, dir 0700) and
stores only `sha256` in `tokens`. Every API call carries `Authorization: Bearer <token>`; the server
maps it to `(label, role)`. Reads need any valid token (the web view asks for the viewer token once
and keeps it in browser storage). No shared token, no password users, no open registration.
`konstant board tokens --rotate <role>` (owner) replaces a token.

Factory identities (level 5, docs/LEVEL5.md §2.2): `board init` also mints tokens with their own
LABEL - `planner`, `dod-reviewer`, `scenario` (role worker) and `factory` (role orchestrator) -
as `var/secrets/<label>.token` (`board/policy.py` `IDENTITIES`); `board tokens --rotate ROLE
--label LABEL` replaces one, `--as LABEL` acts as one. The board compares labels: `approve` is
refused to the job's requester (`the requester cannot approve its own DoD`), `claim` and `close`
to a label that posted the job's `dod-review` (`POST /api/jobs/{id}/dod-review`, only the
`dod-reviewer` identity, before any claim) or sealed its holdouts (the owner or the `scenario`
identity seal). Under one OS user these labels stay apart because a factory phase runs in the
jail and reads only its own identity's token (§7.2).

The CLI picks a token by `--as <role>` (default `[client] default_role`, `orchestrator`). Role
separation on one machine is procedural, and the design says so plainly:
- the task runner starts harness phases with `KONSTANT_IN_TASK=1` and `KONSTANT_ROLE=worker`; under
  it the CLI acts as `worker` by default and refuses every token but `worker` and `viewer`
  (F-12: phases had held the orchestrator token, which filed and claimed their job);
- the board refuses a verdict from the identity that closed the job, and a review from the
  identity that filed, claimed or closed it (any role);
- for real separation run `konstant verify` as a second OS user that cannot read the
  orchestrator/worker tokens: then the verifier never executes the closer's `verify_cmd`, only a
  DoD `VERIFY_CMD:` (F-10); `konstant doctor` reports which mode is in effect. Agent code a DoD
  command runs still runs as that user; only the jail (§7 step 4) masks its token.
- The redactor also knows the role tokens themselves (registered at board start and rotate), and
  `NAME=value` assignments whose name contains token/secret/password/key (F-14). The DB and
  `var/` are private to the owning user (0600/0700; the CLI runs with umask 077, harness phases
  with the caller's own umask; F-25). Request bodies over 1 MiB answer 413; job lists omit
  brief, acceptance and evidence (F-22). The auth scheme `Bearer` is case-insensitive.

## 6. Task gate

### 6.1 One source: `catalog/types.yaml`

```yaml
version: 1
review_types: [review, docs, design, research]  # close by `job review` into `reviewed`
types:
  code:
    agent: coder
    deliverable: build                          # build | verdict | doc
    summary: Application or library code, including bug fixes and refactors.
    keywords: '\b(implement\w*|build|write|create|develop|refactor|fix|patch|module|...|bug)\b'
    workflow: code                              # catalog/workflows/code.md
    skills: [coding-discipline, test-design, reuse-first, workspace-layout, spike, api-design]
    done_rows: true                             # proof-of-absence + surface rows
    read_only: false
    phases:
      - {agent: architect, step: open,  task: placement plan; nothing is written before it}
      - {agent: coder,                  task: build the deliverable and commit it}
      - {agent: tester,    verdict: TEST-verdict.md,   task: independent tests against the DoD}
      - {agent: reviewer,  verdict: REVIEW-verdict.md, parallel: true, task: adversarial review}
      - {agent: architect, step: close, verdict: ARCH-verdict.md, task: architecture doc matches reality; hygiene holds}
  # frontend, infra, test, security, review, research, docs, design: same schema
# phase keys: agent, step (open|close), verdict (NAME-verdict.md), parallel, when (changed:
# read-only types run the architect only when the run changed a project file), task
surfaces: [backend, db, frontend, api contract, tests, docs, deploy]
verdict_words: {pass: [PASS, SHIP], fail: [FAIL, FIX, RECONSIDER], blocked: [BLOCKED]}
small_shapes: ['^\s*(what|why|how|is|are|does|do|can|could|should|which|who|when|where)\b.*\?\s*$',
               '^\s*(status|ping|hello|hi|thanks|ok|show|list|explain|summari[sz]e)\b']
deliverable_signal: '\b(file|module|package|repo|report|document|tests?|deliver|ship|\.py|\.md|\.sh|\.ya?ml)\b'
imperative: '^\s*(?:please\s+)?(audit|review|inspect|assess|critique|implement|build|refactor|secure|harden|pentest|research|document)\b\s+\S+'
```

Note: the type order in the file IS the classifier order (security, review, docs, infra,
frontend, research, design, test, code). A phase is a **producer** when it has no `step` and either
no verdict file or is run by the type's own agent (a `test` run's tester writes the suite AND its
verdict); a phase with a verdict file is **verifying**. `catalog.py` validates the phase keys,
regexes, unique verdict files per type, a producer per type, and that every phase agent is the
agent of some type.
Each type also carries `workflow` (a `catalog/workflows/<name>.md`) and `skills` (names under
`catalog/skills/`), and a top-level `roles: {orchestrator: {skills: [...]}}` gives the skills of the
one agent that is no type's producer; `catalog.py` validates both on every load.

Consumers: `gate/classify.py` (keywords, small shapes, order = list order, `code` last as the
catch-all), `gate/render.py` (phases, verdict files, workflow name), `gate/check.py` (verdict files,
`read_only`, `done_rows`), board (`type` validation, `review_types`), `agents/generate.py` (agent ↔
type, skills, routing table in CLAUDE.md). `catalog.py` validates on load: every phase agent has
`catalog/agents/<agent>.md`, every skill has `catalog/skills/<name>/SKILL.md`, every workflow file
exists, every type has exactly one producer agent and that agent is the type's `agent`, every agent
is the `agent` of exactly one type (orchestrator excepted). A violation stops every consumer.
The structural rules are checked on every load; the file cross-references are checked with
`check_files=True` by the consumers that use those files (gate, generator, doctor). The board needs
only type names and `review_types`, so it loads without them. Root lookup: `[catalog] path`, env
`KONSTANT_CATALOG`, `<workspace>/catalog`, then the source tree.

### 6.2 Classifier (`konstant task classify`)

Deterministic, no model: an explicit `[type:x]` tag wins (unknown tag → NOTE + keyword fallback,
`why=unknown-tag:<x>`); else a question (the FIRST small shape, under 400 chars) that is not a
request ("can/could/would/will you ...?") → `small`; else the first type whose keyword regex
matches, when the task also carries a deliverable signal or is ≥ 400 chars (`keyword:<word>`);
else a bare imperative naming a target ("review the parser", "add retries to the client") → that
type (`imperative:<word>`); only then the other small shapes (a message that is only a chat
opener; a read-only opener like "show"/"list") → `small`; else no deliverable signal → `small`
(`no-deliverable`); else `code` (`deliverable-signal`). `--type` on gate/run forces a type
(`why=flag`). A task ending in `?` is NOT small by that fact alone (a self-answered imperative
must still be gated). F-16: the earlier order (every small shape first) let "ok, implement X"
and "Can you implement X in a.py?" run ungated.

### 6.3 Gate block and run record

`konstant task gate "<task>" [--job N] [--out DIR] [--harness NAME] [--cwd DIR] [--session ID]
[--file-job]` prints the task prefixed with a block
(`=== TASK GATE (type) ===` … `=== END TASK GATE ===`) stating only run-specific mechanics: type,
numbered phases with agent + verdict file (and where the orchestrating session finds the agent
profiles: `.claude/agents/` for Claude Code, `.dsh/agents/` + `subagent` for dsh, `--harness`), the OUT dir, the `konstant task judge` command, the
DONE.md shape, the 3-cycle cap with BLOCKED rows, "never write or edit a verdict file yourself",
the git last mile, and a pointer to skill `workflow-<type>` for everything else. Budget: 3,300
characters for the `code` block (a test keeps it). It also writes the run record
`var/runs/<stamp>-<slug>/record.json`: task, type, why, mode (`interactive` from `task gate`,
`runner` from `task run`), phases, `read_only`, `done_rows`, `exercise`, verdict words, OUT, project
path, git top + base commit, start epoch, job id (+ its acceptance), the `[gate]` settings in force,
and the judge and check commands (`<python> -m konstant task judge --run <run>` /
`... task check <run>`, absolute so they work from any cwd). The check needs nothing but the run
dir. `--job N` must name an existing open job (a reachable board that says the id does not exist →
exit 2; a verified/reviewed/cancelled job → exit 1; an unreachable board → a warning).
A small task is printed unchanged and writes no record.

OUT defaults to `<project path>/.audits/<YYYYMMDD-HHMMSS>-<slug>/out/` (`<run dir>/out/` when the
task names no project); scratch goes under `OUT/.tmp/`. Budget is measured with the python path,
run dir and OUT replaced by fixed tokens (`render.block_len`).

### 6.4 DoD check (`konstant task check <run>`), rules kept and dropped

Exit: `0` MET · `3` UNMET (one reason per line) · `4` BLOCKED (nothing unmet, but DONE.md honestly
reports unverifiable claims; never resumed, never MET) · `5` the check itself failed · `2` usage.

| rule | kept as | statement |
|---|---|---|
| verdicts | `rules/verdicts.py` | fresh verdict files end with exactly one `# VERDICT: <word>` line; at most one `# JUDGED:` line |
| phases | `rules/phases.py` | every verifying phase has a fresh verdict file named for it; a cycle writes a new suffixed file (`-c2`); the newest decides; after 3 cycles a non-pass verdict counts as BLOCKED |
| judged | `rules/judged.py` | a decisive PASS verdict's `# JUDGED: <sha>` equals the content hash of OUT (minus verdicts/DONE/CYCLES/.tmp) + the git diff of the project tree vs the run base (a project that is not a git tree: every project file outside OUT), recomputed by replaying the args recorded with the pin; mismatch = edited after judging (the changed paths are named); unrecorded args (`PIN-ARGS-UNRECORDED`) / base mismatch (`PIN-BASE-DIFFERS`) = UNMET by name; the judge refuses an EMPTY state (exit 2) |
| done | `rules/done.py` | DONE.md rows `ID | claim | STATUS | evidence`, STATUS in PASS FAIL BLOCKED N/A UNVERIFIED; the header is only a line whose first four cells are exactly those names (F-09); FAIL/UNVERIFIED/placeholder evidence/N/A without reason = UNMET; ≥1 PASS row; with a job, one `DoD-<n>` row per row of the job's DoD (`board.dod.dod_rows`), PASS or BLOCKED, never N/A (F-21); `DECLINED | <claim> | job <id>` excuses an EXCUSABLE condition only when the claim quotes it (≥2 contiguous shared words, claim ≥3 words) AND job `<id>` carries an owner-role note/approval `DECLINED: <the same claim>` read from a reachable board (F-01: a quoted "owner statement" and "any existing job" were text the close-out agent could author); offline or unreachable = unresolved (fail closed); never excuses the rules verdicts, phases, judged, tests, verified, authorship, holdouts; `DECLINED`/`DISPUTE` rows are not matrix rows |
| tests | `rules/tests.py` | the test command passes: `[gate] test_cmd` read from the WORKSPACE config, never the record (F-06); `auto` = `pytest` over `test_*.py` under OUT and over the project when it holds Python test files outside OUT (F-18); every run of agent code goes through `konstant.jail` (bubblewrap: read-only root, writes to OUT/project/private tmp, secrets + credential dirs masked, no network) when it works |
| last mile | `rules/lastmile.py` | in a git tree: no untracked file created during the run outside OUT/.audits/.tmp; no marker words (`TODO`, `FIXME`, `XXX`) added to source since start; changed test files pass |
| hygiene | `rules/hygiene.py` | non-test source in OUT > 400 lines needs a `reason` in its first 5 lines; a project source file the run grew past 600 lines without one = UNMET (thresholds configurable) |
| absence | `rules/done.py` | build types: ≥1 `N<n>` proof-of-absence row or `N1 | proof of absence | N/A | <reason>` |
| surfaces | `rules/done.py` | build types: one `surface <name>` row per surface, PASS or N/A with reason |
| exercise | `rules/exercise.py` | Python only: tests under OUT enter at least one function of every non-test `.py` in OUT (traced run) |
| holdouts | `rules/holdouts.py` | the verifier's newest holdout result since the run start: each failed holdout UNMET `holdout H<n> failed (hint: ...)` (owner producer), a LEAK or a commitment mismatch BLOCKED; a `DISPUTE \| H<n> \| <why>` row in DONE.md is BLOCKED (an owner decision, never resolved automatically, excuses nothing), a malformed one UNMET; unexcusable (§7.1) |
| verified | `rules/verified.py` | the run's job, once closed, has a `konstant verify` verdict newer than the run start; FAIL = UNMET, BLOCKED = BLOCKED; a board that cannot be read = UNMET (fail closed); `task check --offline` skips the rule with a warning (the evidence the runner closes with uses it, so the verifier's re-run does not wait on its own verdict) |
| authorship | `rules/authorship.py` | runner mode: EVERY verdict file (superseded cycles too) must have been created by a run of the verifying phase it names (phase manifests, §6.5) and touched by no other phase run, and its content must equal the sha256 the last phase that touched it recorded (F-05: a change outside every phase window); otherwise UNMET `AUTHORSHIP:` (also for a verdict file no phase run created). No re-run can undo it: the loop stops (owner `none`). Inside a parallel group (one shared snapshot) a verdict file is credited by NAME to the member it names. Interactive mode: an unattributed WARNING |
| cleanup | `rules/cleanup.py` | DONE.md carries `CLEANUP: <what was moved/removed and where>` or `CLEANUP: NONE-NEEDED`; `[gate] cleanup = warn` (default) or `fail` |

Every finding carries an owner (`producer`, `orchestrator`, `verifier:<file>`, `none`) that the
loop resumes. Rule order is fixed because the repeat-stop compares the FIRST reason: verdicts,
phases, authorship, judged, done (+absence, surfaces), cleanup, tests (+exercise), lastmile,
hygiene, holdouts, verified; the DECLINED filter runs last.

What the check trusts (F-06, F-11): only run dirs directly under `<workspace>/var/runs/` (the
workspace of KONSTANT_HOME / `--config` when the caller has one, else the one the run dir sits
in); from the record only run facts (task, type, OUT, project, base, start, job + acceptance,
mode); phases, read_only, done_rows, exercise, verdict words and the `[gate]` settings are
re-derived from that workspace's catalog and `konstant.toml`. konstant's own git reads in the
rules (judged, hygiene, lastmile, `project_changed`) never run `git diff`/`status`/`show`: the
drift is listed with plumbing (`ls-tree`, `ls-files`) and hashed by konstant on the raw bytes,
added lines come from a Python diff of the `cat-file` blob, and every git call runs with system
and global config off, no fsmonitor, no hooks, no transports (F-04).

Left out, with reason: a transcript bash lexer (it produced repeated false UNMETs in
practice); transcript-dialect authorship parsing (tied to one harness's event format; replaced by
phase manifests); leaf/HANDBACK routing (exists only when children inherit the orchestrator's
gate; the runner knows each phase's role); research close-out lines into external memory stores
(deployment-specific); a legacy cutover date for JUDGED; a deliverable-pair env channel (no
nested gates in v0.1); a reduced infra phase set for board-backed jobs (every job is verified by
`konstant verify`); a model-endpoint pre-flight before spawns.

### 6.5 Phase runner (`konstant task run`) and the DoD loop

`--harness NAME` (an adapter: claude, codex, gemini, dsh) runs every phase of that run on
that adapter; `--harness "<template>"` stays a command template.

The runner is the enforcing mode: konstant, not the model, drives the phases.

1. Classify; `small` → one harness run with the task as-is in the project dir (the workspace
   without `--project`), no loop, exit = harness exit; a small task with `--job` exits 2 (an
   ungated run never closes a job; force a type with `--type`; F-26).
2. Write the run record (§6.3); take the project's lock `var/locks/project-<hash>.lock` (flock,
   held for the whole run: a second run on the same project exits 2; F-28); optional `--job N`
   is claimed if queued. The runner makes itself a child subreaper (Linux) and composes every
   agent profile ONCE into memory and `<run>/profiles/` (F-08: a phase that edits `catalog/`
   cannot change a later phase's prompt).
3. For each phase in order (consecutive `parallel: true` phases run concurrently, up to
   `[harness] max_parallel`; `max_parallel = 1` runs every phase as its own group, F-15): build
   the prompt = the snapshot profile + phase brief (task, DoD, OUT, the verdict file name, the
   judge command for verifying phases, "you are a leaf: never spawn agents"); snapshot OUT (path
   → sha256); run the harness (§9); SIGKILL every process the phase left running (a detached
   process is re-parented to the subreaper, so it stays findable; `gate/reaper.py`, F-05);
   snapshot again; write `phases/<n>-<agent>-c<cycle>.json` with created/modified/deleted files,
   the sha256 of each verdict file it left, exit code, duration.
4. Back-edge: a verifying phase whose verdict is FAIL/FIX/RECONSIDER re-runs the producer with the
   verdict text as context, then the verifiers again (new suffixed verdict files). Cap: 3 cycles.
5. Close-out phase: the `orchestrator` profile writes DONE.md and CYCLES.md from the artifacts.
6. `konstant task check`. UNMET → re-run the phase that owns the first reason (producer: the
   producers, then every verifier that ran, with new cycle files; `verifier:<file>`: that phase;
   orchestrator: DONE.md), then the close-out, up to `[gate] max_resumes` (3); stop early when
   the first reason repeats unchanged between two rounds (whitespace, timestamps, shas and the run
   paths normalised) or when its owner is `none` (AUTHORSHIP). BLOCKED is never resumed.
7. MET with `--job` → `konstant job close` with evidence = `VERIFY_CMD: <python> -m konstant task
   check --offline <run>` + `VERIFY_EXIT=0` + the DONE.md rows (`<run>/evidence.md`), then
   `konstant verify` when `[gate] verify_after_close = true`; the run is linked to the job in the
   `runs` table. Exit: 0 MET (and verify PASS), 3 UNMET or verify FAIL, 4 BLOCKED, 5 check error.

A job with sealed holdouts (§7.1) runs in factory mode (§7.2): every phase confined in the jail on
any harness (`Adapter.confines` with `factory`), the job claimed, then its clone made and used as
the run's project. Without a working jail (`[gate] jail`, bubblewrap) the run exits 2 `holdouts
need a confined phase` before it claims anything; `task gate` refuses such a job the same way (an
interactive session is not confined). Its phase prompts say only THAT holdouts exist and how many (`KONSTANT-HOLDOUTS: <n>`
and a short "Holdouts" paragraph); the close evidence carries `COMMIT=`/`BASE=` (§4.3).

Read-only types: the conditional opening architect never runs under the runner (nothing is known
to change before the work); the closing one runs when the project changed. The cycle log the
runner keeps is handed to the close-out prompt as `KONSTANT-CYCLE-ROW:` lines (one per cycle),
and with a job the DoD rows as `KONSTANT-DOD-ROW: DoD-<n> | <row>` lines (the gate block lists the
same ids for interactive runs).

Interactive mode (a person or an orchestrating session drives subagents): `konstant task gate`, the
generated CLAUDE.md tells the session to spawn one subagent per phase using the named agents, then
`konstant task check`. Same rules, minus mechanical authorship.

Signals: SIGINT/SIGTERM stop the running harness process group and end stderr with
`konstant task: KILLED (<sig>) after <n>s — DoD UNMET`, exit 128+signal.

### 6.6 Gated sessions: job binding, `task close`, the dsh plugin

A person's own dsh session gets the loop of the runner through a dsh plugin, `konstant-gate` (`harnesses/dsh_gate/index.ts`, TypeScript on dsh's
cordis API, vendored build `konstant-gate.mjs` whose first line records the sha256 of the source;
the build imports no dsh package at run time and calls konstant with argv, no shell). `agents
sync` copies it to `.dsh/konstant-gate.mjs` and writes `.dsh/konstant-session.patch.yml` (the
plugin row with `[gate] max_resumes`, `verify_after_close`, `file_job` and `[board.policy]
max_rounds`) and `.dsh/agents/<agent>.md` (the composed profiles; dsh has no named subagent
profiles). `konstant dsh APP [ARGS]` (`cli/dsh.py`) starts `dsh --profile APP` with both patches,
`DSH_HOME` in `var/harness/dsh/session/` and the session in the project's directory. The session
is unjailed, so before the start it refuses with exit 1 (fail closed; G-01/G-02/G-05): when `agents sync --check` for dsh finds drift (the plugin and patches it
loads must be konstant's, byte for byte); when a profile of the session home holds installed
packages (`node_modules`, `.dsh-module-fallback`: they resolve before dsh's own bundles); and when
`harnesses/dsh.py compose_layers` (the app, both patches, the session environment,
`--dump-config`, no model call) cannot read the composition or finds a foreign layer.
`compose_layers` judges the COMPOSED result: a baseline composes the profile with a fresh, empty
DSH_HOME and no patch (it must name a layer, and dsh must have created that home's profile, else
a launcher forces its own home); the real composition must name each of konstant's patches; every
other origin (an id-patch or insert-only layer, a home layer, a bundle the baseline did not
compose) is foreign. Phases cannot write the session home: `var/harness/` is konstant machinery
(§9). `--dry-run` runs no dsh.

- `agent/pre-step`: every user message of the session that is not empty, not a `/`-command and
  not from a delegated child (`origin = subagent` or delegation depth >= 1) goes through `konstant
  task gate --json --harness dsh --cwd <session cwd> --session <id> [--file-job] -`; a typed task's
  text is replaced in place by block + text (+ `[job:N]` when bound); a failing gate passes the
  text UNGATED with a notice. Inside a runner phase (`KONSTANT_IN_TASK=1`) the plugin installs
  nothing. A child's bash gets `KONSTANT_ROLE=worker KONSTANT_IN_TASK=1` (dsh's `shellEnv`).
- `agent/turn-stopping`: `konstant task check --offline <run>`; UNMET steers a nudge into the same
  turn up to `max_resumes`, stopping when the normalised first reason repeats; BLOCKED and check
  errors end with a notice; MET with a job runs `konstant task close <run>`; a verify FAIL is
  steered back with the verifier's reasons on its own budget (`max_rounds`), the UNMET budget
  reset; MET with `file_job` and no job = UNBOUND. Every decision is logged to
  `var/logs/konstant-gate.log`.
- Job binding (`cli/task_session.py`): `--job N` or a `[job:N]` tag; else `--session ID`'s open
  bound job (`var/sessions.json`); else with `--file-job` a new job under the project of `--cwd`
  (the task text is the brief, so the board refuses it without a DoD). With `--session` the bound
  job is claimed when queued or blocked.
- `konstant task close RUN`: the offline check must be MET (else its exit code and reasons), the
  job is claimed again when a verify FAIL sent it to `queued`, then `close_and_verify` (§6.5 step
  7). `--json` prints `verdict`, `reasons`, `status`. Exit as §6.5 (0 PASS, 3 FAIL, 4 BLOCKED, 5).

The plugin reads no transcript: in a session, verdict authorship stays a warning.

## 7. Verifier (`konstant verify`)

`konstant verify <job> [--dry-run] [--json] [--no-rerun]` and `konstant verify --pending`. Runs with
the verifier token. Steps:

1. The job must be `completed_unverified` (else exit 2, naming the state).
2. Collect `PROBE:` lines from the job's acceptance (source `dod`) and from the stored evidence
   (source `closer`). Format: `PROBE: <command> => <regex>`; `PROBE-REFUSED: <command> => <expect> =>
   <reason regex>` asserts that the allowlist refuses a line (never run).
3. Parse each command with `shlex` (no shell). Every token must match a safe-character class
   (`; & | $( `` ` `` > < newline` refused before shape matching). The argv must match one shape:

| shape | constraint |
|---|---|
| `test -e|-f|-d PATH` | output is the literal `ok` / `absent` |
| `ls -ld PATH`, `stat -c FMT PATH`, `sha256sum PATH` | — |
| `grep -c PATTERN PATH` | pattern is an operand, never an option |
| `git -C TREE rev-parse HEAD|--verify REF`, `git -C TREE log -1 --format=%H|%ae|%s REV`, `git -C TREE branch -r --contains SHA`, `git -C TREE blob-sha256 REV:PATH` | plumbing only; git env pinned: no system/global config, no prompts, `core.fsmonitor=false`, no hooks, `protocol.allow=never`, empty credential helper, `gpg.program=/bin/false`. F-04 removed `status --porcelain` (a repo's clean filter runs on stat-dirty files) and `ls-remote` (a repo's `uploadpack` runs): repo-local config cannot be switched off, so only shapes that never convert worktree content or talk to a remote stay |
| `curl -s [-o /dev/null -w %{http_code}] URL` | GET only; host in `[verify] url_hosts` (default loopback) |
| `systemctl [--user] is-active|is-enabled UNIT`, `systemctl [--user] show UNIT -p PROP` | — |
| `docker inspect -f FMT NAME` | — |
| `sqlite3 -readonly DB "SELECT …"` | one statement, starts with SELECT |
| `<binary> --version` | binary resolved on PATH |
| `konstant job show ID --json` | board read-back |

   PATH/TREE/DB operands must resolve (realpath) under `[verify] path_roots` (default: the workspace
   and each project path), never into the workspace's `var/` (F-29), and the RESOLVED path is
   what runs (F-35). A project path itself may not be `/`, the user's home, the workspace or an
   ancestor of it, or inside `var/` (`project add` refuses it; F-13). The regex must be non-trivial (`.*`, `.`, `^`, `\w`, `[0-9]+` and any
   regex that matches the empty string are refused). Timeout `probe_timeout_s` (20), output cap 64 KiB.
   A non-match is a CONTRADICTION; a refusal/timeout/error is UNVERIFIABLE.
4. Re-run: the command is the DoD's `VERIFY_CMD:` line when it has one (written by the requester),
   else the closer's `verify_cmd` - and that only in procedural mode: when this OS user cannot read
   an existing orchestrator/worker token (OS-separation mode) the closer's shell is never executed
   by the verifier (F-10). It runs with `/bin/sh -c` in the project dir, a scrubbed env (no
   `KONSTANT_*`, no token variables), timeout `rerun_timeout_s`, inside `konstant.jail` when
   bubblewrap works (`var/secrets/` and credential dirs masked, writes only to the project dir, an
   own pid namespace; `[gate] jail`). Without the jail it runs as the invoking user, the same reach
   the agent had. Disable with `[verify] rerun = false` or `--no-rerun`. If `evidence.commit` is
   set, it must be reachable from the project's HEAD, else FAIL.
5. Settle: **PASS** = (re-run exit 0, or no re-run) AND ≥1 `PROBE` of the DoD (source `dod`)
   matched AND every probe matched · **FAIL** = re-run exit ≠ 0 or any contradiction ·
   **BLOCKED** = nothing independent verified (no DoD probe matched: a re-run or the closer's own
   probes replay the closer's claim; F-02), or only unverifiable probes.
6. Record a `verifications` row and a `verdict` trail row (kind reserved for verifier/owner), then the
   transition from §4.2. `--dry-run` prints the result and writes nothing.

Holdouts (§7.1) run after the probes and the re-run and extend step 5: a commitment mismatch or
a LEAK is BLOCKED first; a failed holdout or a LEAK-SUSPECT is FAIL; an unrunnable holdout is
BLOCKED; PASS needs the level-4 PASS AND every sealed holdout passed (holdouts alone never pass a
job). The result's `holdouts` key and `verifications.holdout_json` carry ids, pass/fail, timings,
the commit and the digest only.

Exit: 0 PASS, 3 FAIL, 4 BLOCKED, 2 not found / wrong state, 1 refusal; `--pending` exits 3 if any
job FAILs, else 4 if any is BLOCKED, else 1 if one errored, else 0. Decisions: a re-run that
times out is unverifiable (BLOCKED), not FAIL; `--as owner` posts with the owner token (the
closer rule still applies), otherwise the verifier token is used and `--dry-run` reads with the
viewer token; `test`, `curl`, `sqlite3` and `blob-sha256` run natively in Python (no binary
needed, no redirects followed, sqlite read-only with a SELECT-only authorizer); every probe runs
with a scrubbed env and git pinned (`GIT_TERMINAL_PROMPT=0`, no fsmonitor, no credential helper,
`gpg.program=/bin/false`, `--no-show-signature`). The JSON result carries `job`, `display_id`,
`verdict`, `reasons`, `probes`, `rerun`, `dry_run`.

`konstant job lint <brief>` flags DoD rows that describe live state but carry no PROBE, and PROBE
lines the allowlist would refuse (exit 1, `PROBE REFUSED:` lines; roots = the verifier's own root
builder over the board's projects, `[verify] path_roots` + `projects/` when the board is down) —
at filing time, before the work starts. `job add` prints the same PROBE warnings (F-30).

### 7.1 Holdouts (level 5, pillar A; docs/LEVEL5.md §3)

A holdout is a black-box acceptance scenario for one job, sealed before the producer claims it,
stored where no producing phase can read it, and run only by the verifier on the commit the job
closed with.

- **Format** (`holdout/lint.py`): one file per scenario, `KEY: value` lines (`#` lines are
  comments): `SCENARIO`, `KIND` (`proof`: must fail on the base; `regression`: must pass before
  and after), `RUN` (shlex-split and run as an argv, never through a shell: control characters
  and shell operators outside quotes are refused, and so is a test runner), `EXPECT_EXIT`,
  `EXPECT_OUT` (the whole stripped stdout) or `EXPECT_RE` (fullmatch of it, non-trivial), `HINT`
  (the only text a failure reveals; it may not hold a token of RUN or of the expectation) and
  `CANARY` (`khc-` + 20 hex, written by `holdout add` when absent).
- **Seal** (`holdout/store.py`, `konstant holdout add JOB --file F [--file F ...]`, owner): lint
  (keys, safe RUN, no test runner, non-trivial, **held out**: no expectation literal or quoted RUN
  argument of 4+ characters in the brief or DoD, hint), the set rule over sealed + new (at least
  `[holdout] min_per_job`, at least one `proof`, unique canaries), then the **negative control**:
  every new scenario runs on the project's current HEAD the way the verifier will run it
  (`VACUOUS: H<n> passes before the work`, `REGRESSION FAILS`, `UNRUNNABLE`). Then the board
  stores `sha256(file)` per scenario (`POST /api/jobs/{id}/holdouts`, only while the job is
  `queued`/`waiting_approval`; it marks the job `holdout_required`) and the file is MOVED into
  `var/holdout/<job>/H<n>.scenario` (0400 in 0700). A source inside the workspace is refused.
  `holdout show` reads the store directly and is refused inside a task run; no route serves content.
- **Reach** (`machinery.SEALED`): the jail masks `var/holdout/` (`jail.hidden`), Claude Code's
  settings deny `Read` on it and read-deny it in the sandbox, the codex profile denies it, the
  gemini policy denies `read_file`/`read_many_files`/`glob`/`search_file_content` under it, and
  probes never read `var/`. A job with holdouts never runs on an unconfined phase (§6.5).
- **Verifier** (`verify/holdout.py`, from `verify_job`): the commitment (store file hash = the
  board's sha256, else `holdout commitment mismatch: H<n>`, BLOCKED); the leak scan
  (`holdout/leak.py`: each canary as raw bytes in the diff `BASE..COMMIT`, OUT, the phase logs and
  prompts of the job's runs and the trail -> `LEAK: canary of H<n> found in <path>`, BLOCKED, the
  set is burned; a distinctive literal on an added line -> `LEAK-SUSPECT`, FAIL); every sealed
  holdout sealed before the round's claim; then the tree of the evidence `COMMIT=` is materialised
  from `ls-tree`/`cat-file` into a private temp dir (no checkout, filter or hook), each RUN runs in
  `jail.session` with **no network**, that dir bound at the project's own path, the store masked
  and the env scrubbed, timeout `[holdout] run_timeout_s`; stdout and the exit code are matched
  outside the jail; the temp dir is deleted. Findings are redacted to `holdout H<n> failed (hint:
  ...)`.
- **Exposure budget** (board, on the verdict): a FAIL round caused by holdouts counts against the
  sealed set; after `[holdout] max_failed_rounds` the set is worn and `retired` (the claim guard
  then holds the job until a fresh set, generation n+1, is sealed); a second worn set blocks the
  job for the owner. A LEAK burns the set (the job stays `completed_unverified`).
- **DECLINED / DISPUTE**: the `holdouts` rule is unexcusable; a `DISPUTE | H<n> | <why>` row is
  BLOCKED, an owner decision.
- Limits (LEVEL5 §3.8): holdouts raise the cost of cheating, they do not prove correctness; under
  one OS user a process you run unjailed can read the store (`[holdout] store` outside the
  workspace for a second OS user; `doctor` reports which applies).

### 7.2 Factory mode: confinement, identities, job clones (level 5; docs/LEVEL5.md §2)

A run of a job with sealed holdouts is in **factory mode** (`cli/task_run.py` `_run_factory`).

- **Every phase confined, whatever the harness** (`harnesses/base.py` `Adapter.confine`,
  `jailed`): claude, codex, gemini, dsh and an explicit command template (run as the `command`
  adapter) all start inside konstant's jail: root read-only; writable only the job clone, OUT,
  the phase TMPDIR (the jail's own empty `/tmp` unless the workspace lies under `/tmp`) and the
  harness's per-phase home; every machinery path read-only inside those; `var/secrets/` masked
  except the phase identity's token and the read-only viewer token; `var/holdout/`, the
  credential and agent homes masked. claude, codex and gemini get a FRESH home per phase
  (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME` under `var/harness/<name>/phases/`,
  removed after the phase: `Adapter.relocatable_home`), into which only their own credential
  file (`~/.claude/.credentials.json`, `~/.codex/auth.json`) is bound read-only. dsh confines
  every phase anyway. Without a working jail a factory run exits 2 `holdouts need a confined
  phase`, and `Harness.run` refuses a factory phase it could not confine. `task gate` (an
  interactive session) still refuses a holdout job.
- **Claude Code's sandbox nested** (live-checked in L5-2): it runs inside the jail when a nested
  bubblewrap starts there (`jail.nests`), socat is installed and the phase has the jail's short
  private `/tmp` (its bridges are unix sockets under `TMPDIR`; a long `TMPDIR` fails them).
  Otherwise the phase gets the generated settings minus the `sandbox` block (Claude Code's sandbox
  off, the jail the boundary; `harnesses/claude.py` `without_sandbox`): a sandbox that cannot
  start would otherwise deny every Bash call (`allowUnsandboxedCommands = false`). `doctor` row
  `claude sandbox` says which applies.
- **Identities**: each phase acts as one identity (`KONSTANT_IDENTITY`, default `worker`; §5); the
  in-task client uses that identity's token for worker requests; codex's profile denies every
  other token file.
- **Job clones** (`factory/clone.py`, migration `0003_workdir.sql`): the job's first claim makes
  the board record `jobs.workdir = <project path>@<job id>` and `jobs.workdir_base` = the target's
  `HEAD` commit (computed by the board with plumbing, recorded once: trigger
  `jobs_workdir_once`); a holdout job whose project is no git repository cannot be claimed. The
  runner then builds the clone with plumbing only (`git init --template=`, the target's object
  store as an alternate, `update-ref`, the tree written from `ls-tree`/`cat-file`, `read-tree`),
  refuses a tree path into `.git`, keeps an existing clone of the same job and base on a re-claim,
  and makes it the run's project (record `project`, `git_base` = the clone base, OUT under it, the
  one-run lock on it). The target is read-only in every phase jail (a `self-ship` producer's
  `git update-ref` in it is denied).
- **Verifier**: `verifier.job_dir` = the clone when recorded (re-run, holdouts, leak scan); a DoD
  `PROBE:` may name `{workdir}/...`, substituted with the clone (workspace-relative) BEFORE shape
  matching, so the allowlist and path roots judge the resolved path; `job lint` checks such a path
  as a project path. The negative control of a re-sealed set runs on `workdir_base`.
- **doctor** rows `factory jail`, `factory harness` (per harness: home relocation), `claude
  sandbox`, `identities`.

## 8. Catalog, generator and generated surfaces

Sources (in git): `catalog/agents/<agent>.md` = frontmatter (`name`, `description`, `tools` hint)
+ the role body (discipline, what it never does, output shape). `catalog/doctrine/base.md` = shared
principles (evidence levels VERIFIED/TESTED/INFERRED/UNVERIFIED/CONTRADICTED; paste read-backs, never
retype; label negatives; two honest attempts then BLOCKED; never self-verify; never put a secret in
an artifact; smallest change; the never-equate list). `catalog/doctrine/contracts/<deliverable>.md` =
the build/verdict/doc contract + file-hygiene text. `catalog/agents/orchestrator.md` = intake →
classify → gate → fan out → integrate → check → close → verify → report; escalation and
final-report format.

`konstant agents sync [--check]` (`agents/generate.py`) writes:

| output | composed from |
|---|---|
| `.claude/agents/<agent>.md` | agent frontmatter + base doctrine + deliverable contract (from types.yaml) + skills list for its type |
| `.claude/skills/<skill>/SKILL.md` | copied from `catalog/skills/` (plus any `scripts/`) |
| `.claude/skills/workflow-<type>/SKILL.md` | `catalog/workflows/<type>.md` + rendered phase table |
| `.claude/settings.json` | workspace-scoped reach (design decision, §9; `agents/settings.py`): Read/Edit allow rules for `//<workspace>/**` only, the konstant verbs a phase needs, local git verbs, the `[permissions] allow` rules of konstant.toml (test runners); deny rules for konstant's own machinery (`bin/`, `.venv/`, `src/`, `.claude/`, `konstant.toml`, token files, board DB, run records) and for the verbs of other roles (`verify`, `job verdict`, `job approve`, `task run`, `board`, `agents sync`); `blockReadsOutsideWorkingDirectories`; `disableBypassPermissionsMode`; the Bash sandbox with writes confined to the workspace, no unsandboxed retry, and the board-talking konstant verbs excluded |
| `CLAUDE.md` | template: what konstant is, the routing table (type → agent → workflow) rendered from types.yaml, the board loop, "typed task → `konstant task gate` or `konstant task run`" |
| `AGENTS.md` | the same rules for agents.md-compatible harnesses, profiles inlined by reference to `catalog/agents/` (always generated), with an "Operating konstant (any agent, any model)" section: `--json`, `--help`, the exit codes, the board-first rule and what an agent never runs (any LLM agent can drive konstant from this file alone) |

Both top docs include the same command table, `catalog/templates/operate.md.tmpl` (one source).
| `.agents/skills/<skill>/SKILL.md` | the same skills and workflow skills for codex, gemini, dsh and `command` |
| `.dsh/konstant.patch.yml`, `.gemini/settings.json`, `.gemini/konstant-policy.toml` | the reach of a dsh / Gemini CLI phase (`harnesses/dsh.py`, `harnesses/gemini.py`; docs/HARNESSES.md) |
| `.dsh/konstant-session.patch.yml`, `.dsh/konstant-gate.mjs`, `.dsh/agents/<agent>.md` | a dsh session's gate plugin and the agent profiles (`harnesses/dsh_session.py`, §6.6; docs/DSH.md) |

Only the surfaces of the CONFIGURED harnesses are written (`[harness] name` and the
`[harness.types.<type>]` overrides): `.claude/` and `CLAUDE.md` only when claude is one of them;
switching the harness removes the old generated files as stale (a user's own file is never
touched: `.gemini/settings.json` counts as generated only while it holds exactly what konstant
writes). `agents sync [--check] --harness NAME` limits sync or check to one configured harness, and
`--check` reports drift per harness.

Each generated Markdown file carries `<!-- generated by konstant agents sync from catalog/; edit the source -->`
directly after its YAML frontmatter (Claude Code reads agent and skill frontmatter only when it is
the first thing in the file, so the header cannot be line 1 there); `CLAUDE.md`/`AGENTS.md` start
with it. `settings.json` carries no header: JSON has no comments, and an unknown key could fail the
settings schema, which a `claude -p` run answers by silently ignoring the whole file. `--check`
exits 1 listing every drifted, missing or stale file (a stale file is a generated one the catalog no
longer produces; `sync` removes it, files without the header are never touched); doctor runs it.
Re-running `sync` is the only way generated files change; user edits to them are overwritten.
The phase runner builds each phase prompt from the same composed profile (`Generator.agent_prompt`),
so a headless phase and an interactive subagent read identical rules.

## 9. Harness adapters (`harnesses/`, `gate/harness.py`)

Any model should be usable: konstant is the layer ABOVE the harness and never runs a model loop itself; model choice
belongs to the harness. `[harness] name` picks an adapter (`claude`, `codex`, `gemini`, `dsh`,
`command`), `[harness] model` goes through that harness's own model key, `[harness.endpoint]`
points codex and dsh at a local OpenAI-compatible server, and `[harness.types.<type>]` overrides
name/model/command for the phases of that type's agent (the close-out runs on the default; the
phase manifest records `harness` and `model`). Types stay in `catalog/types.yaml`, the choice in
`konstant.toml`. Each adapter (`harnesses/base.py`: `Adapter`) declares its headless argv, env and
per-phase preparation, the surfaces it reads (`files`), how the workspace-scoped reach maps onto
its permission system and what it cannot enforce (`reach`, printed by `doctor`), its model key and
its detection. The per-adapter mapping, the matrix (harness x surfaces x enforcement x local
models x tested live) and the sources are in docs/HARNESSES.md. `gate/harness.py` keeps the
process side (process group, log, timeout, kill) and `HarnessSet` picks each phase's harness. The
`[harness] command` below stays the claude default and the one source of that string; an
explicitly changed `command` is a user template for any name (placeholders below plus `{model}`).
`doctor` has per-harness `harness` and `reach` rows. Every adapter keeps the same guarantees: phases act as `worker`, no edits to
`catalog/` or `.git/config`/hooks where the harness can deny them, user-level settings, hooks,
MCP and memory excluded where the harness allows it (otherwise a `reach` WARN names the leak),
and `[gate] jail` plus the subreaper apply to every harness because they never depended on it.
An adapter may confine its own phase (`Adapter.confine`, and `Adapter.confines` says whether it
does: a job with sealed holdouts runs only on such harnesses); dsh does: its sandbox confines writes
only, so every dsh phase runs inside `konstant.jail` (writes to the project, OUT, the phase's own
dsh home and a private `/tmp`; `var/secrets/` masked except the worker and viewer tokens;
credential and agent homes masked; network on for the loopback board). Its `reads` reach is
`enforced` while the jail works, `none` without it (doctor).

`konstant/machinery.py` is the ONE list (G-01/G-03/G-04) of paths no phase may
write, whatever the harness: the release's code and tools (`bin/ .venv/ src/ catalog/ tests/
install.sh get.sh pyproject.toml konstant.toml`), every generated harness surface (`.claude/
.agents/ .dsh/ .gemini/ AGENTS.md CLAUDE.md`), `var/harness/`, `var/secrets/`, the board DB and
the bookkeeping files under `var/`, run records, and `.git/` (shells that commit get
`.git/config` + `.git/hooks` read-only), and `var/holdout/`. `machinery.SEALED` lists what no phase may
even READ (the holdout store, §7.1). The Claude settings (deny rules + sandbox `denyWrite`),
the codex profile, the gemini policy and the jail's bind rules all read it (`jail.wrap(home=)`
re-binds every machinery path and all of `var/` read-only inside any writable bind, then reopens
the narrower writable binds such as OUT); a test checks each entry against each consumer. The
same module holds the one credential list (the usual credential dirs, every agent CLI's home
`~/.claude ~/.codex ~/.gemini ~/.dsh ...` and the homes `DSH_HOME`, `CODEX_HOME`, ... name), which
the jail masks, the codex profile denies and the Claude sandbox read-denies (codex and Claude keep
their own home minus its credential file, which their sandboxed shells need). Each dsh phase gets
a FRESH `DSH_HOME`/`DSH_AGENTS_HOME` (`var/harness/dsh/phases/<label>-XXXX/`, `Adapter.cleanup`
removes it after the phase), so nothing persists between phases; before the first phase
`Adapter.preflight` composes the phase profile and the run refuses (exit 2) a foreign or
unreadable composition. Earlier builds shared one dsh home between phases, bound all of
`var/harness/dsh/` (the session home included) writable and only WARNed on an unreadable or
foreign composition; the second review showed each of those as a hole (G-01, G-05), so they fail
closed.

```toml
[harness]
command = "claude -p --permission-mode dontAsk --setting-sources project,local --strict-mcp-config --add-dir {workspace} --settings {workspace}/.claude/settings.json {prompt}"
stdin = false                        # true: prompt on stdin, no {prompt} needed
timeout_s = 3600
max_parallel = 2
env = {}                             # extra env for harness runs
```

Placeholders: `{prompt}` (whole prompt as one argv item), `{prompt_file}` (path to a 0600 file in
the run dir), `{agent}`, `{cwd}`, `{run_dir}`, `{workspace}`; substituted in ONE pass per token, so
text inside the prompt is never re-expanded. A prompt over 100 KiB is refused for `{prompt}`
(argv limit) with a message to use `{prompt_file}` or `stdin = true`. The process runs in the
project dir (or the workspace), in its own process group, with `KONSTANT_IN_TASK=1`,
`KONSTANT_RUN=<run_dir>`, `KONSTANT_ROLE=worker`, `KONSTANT_HOME`; stdout/stderr go to
`phases/<label>.log` (timeout → the group is killed, exit 124; a missing binary → 127). konstant
reads files, never the harness's transcript: any CLI agent works.

**Default command = workspace-scoped (design decision: a headless phase may edit files and run
commands only inside the workspace; anything else is denied).** Every name was checked
against the installed `claude --help` (2.1.x) and the official permissions/settings docs, not
guessed:
- `-p` (`--print`): non-interactive; in this mode Claude Code cannot ask, so anything not
  pre-approved must be denied rather than stall.
- `--permission-mode dontAsk` (a listed choice: acceptEdits, auto, bypassPermissions, manual,
  dontAsk, plan): "auto-denies every call that would otherwise prompt"; reads in the working
  directories and tools pre-approved by `permissions.allow` rules still run. So the generated
  allowlist is the whole reach; a phase that needs more fails instead of reaching outside.
- `--setting-sources project,local` and `--strict-mcp-config` (F-20): the operator's
  user-level settings, hooks and MCP servers do not load into a phase (the first security review
  observed the operator's own context leaking into a headless run). User-level CLAUDE.md memory is not a
  settings source; CONCEPTS "Security model and limits" says so.
- `--settings {workspace}/.claude/settings.json`: the docs state that a `claude -p` run never shows
  the trust dialog and does NOT apply `permissions.allow` from an untrusted folder's
  `.claude/settings.json`, and that `.claude/settings.json` is read only from the session's
  working directory (no parent fallback) — a phase runs in `projects/<slug>/`. Passing the file
  explicitly is the documented per-session way to load those rules. A `/path` rule in a file
  passed with `--settings` anchors at that file's directory, so the generated file writes
  absolute `//<workspace>/**` paths, and turns on Claude Code's Bash sandbox (filesystem writes
  confined to the workspace) where the installed CLI supports it.
- `--add-dir {workspace}`: makes the workspace a working directory of the phase, so its files
  stay readable under `permissions.blockReadsOutsideWorkingDirectories`, sandboxed commands may
  write there, and its generated `.claude/agents` and `.claude/skills` load (the docs list skills
  and subagents as loaded from `--add-dir` directories). `--add-dir` takes several values, so it
  stands before another option, never directly before `{prompt}`.
- The sandbox needs `bubblewrap` and `socat` on Linux; without them Claude Code runs Bash unsandboxed
  (`failIfUnavailable = false`, chosen so a host without them still works) and the allow list alone
  decides, which under `dontAsk` still denies every unlisted command. An allowed test runner then
  runs test code the agent wrote with the user's rights, so the allow list does NOT confine a
  phase; `doctor` WARNs in those words. With the sandbox on, `autoAllowBashIfSandboxed = false`
  keeps the allow list authoritative and the usual credential dirs are read-denied (F-19).
- The settings deny Edit on every `.git/` directory and drop `git init` (F-07: a `.git/config`
  edit made an allowed `git status` run a filter; `git init <path>` wrote outside the workspace),
  deny Edit on every path of `konstant/machinery.py` (F-08 added `catalog/`, `tests/`,
  `install.sh`, `pyproject.toml`; G-03 the generated surfaces of the other harnesses
  `.agents/ .dsh/ .gemini/ AGENTS.md CLAUDE.md` and `var/harness/`), and deny
  `--as owner|verifier` on any konstant command line. `task check` stays an excluded (unsandboxed)
  command because it reads the loopback board; the agent code it executes runs in
  `konstant.jail`, the same bubblewrap boundary (F-06).
- Not used: `--dangerously-skip-permissions` / `bypassPermissions` (full user reach), `acceptEdits`
  alone (Bash would still prompt, i.e. fail, with no allowlist).
Live check (one `claude -p` run before the 0.1.0 release): in a freshly installed,
untrusted workspace the default command (plus a cheap `--model` and a JSON event stream, for the
test only) ran an allowed `<workspace>/bin/konstant job list`, while the Read tool on
`/etc/hostname`, `cat /etc/hostname` and `touch /tmp/...` were each denied
(`permission_denials` lists all three). Claude Code printed "Ignoring 45 permissions.allow
entries from .claude/settings.json: this workspace has not been trusted" for the project-level
copy, and the same rules passed with `--settings` still applied, which confirms the reason for
`--settings` above. The default command also passes `--setting-sources project,local
--strict-mcp-config`, so user-level settings and hooks no longer merge into a phase. The test
suite and the fresh-install test prove the runner with the deterministic fake harness (`tests/fixtures/fake_harness.py`) and need
no model; `doctor` checks that the settings file is in sync before a run.

## 10. Install and workspace flow

### 10.1 One-line install (`get.sh`)

Installable with one line, usable by any LLM. The documented line (README,
QUICKSTART) is `curl -fsSL https://github.com/bryn1/konstant/releases/latest/download/get.sh | bash`
(options after `bash -s --`). `get.sh` (repo root; POSIX sh; shellcheck-clean) is also a release
asset (§11):

1. Every line is a function definition except the last, `{ konstant_get "$@"; }`: a truncated
   download is a syntax error (the brace group never closes) or defines functions only, so it runs
   nothing (a test feeds it every 7th prefix and each of the last 120 bytes).
2. Prerequisites before anything is written: Linux or macOS (Windows shells refused, WSL2
   named), not root, `tar`, `gzip`, `awk`, `sha256sum` or `shasum`, `curl` or `wget`, a Python
   >= 3.10 (`$PYTHON`, else `python3`, `python3.14` .. `python3.10`; an old one is named with its
   version); a missing `git` is a warning.
3. Target `./konstant` or `--dir DIR`: refused when it exists and is not empty, when it exists and
   cannot be read or listed (G-06: fail closed), or when its path has whitespace (install.sh
   refuses that too). The download is staged in `DIR/.konstant-get/`, so
   nothing is written outside DIR.
4. Version: `--version V` (a leading `v` is dropped; only `[0-9A-Za-z.+-]`, no `..`), else
   `<base>/latest/download/VERSION`. Assets: `<base>/download/v<V>/konstant-<V>.tar.gz` and its
   `.sha256`. `<base>` = `KONSTANT_RELEASE_URL` or the project's GitHub releases URL (the GitHub
   layout; a mirror or a test server reproduces it).
5. The `.sha256` must name the tarball and carry 64 hex digits; the computed sha256 must equal it
   BEFORE anything is unpacked; every member must sit under `konstant-<V>/` without `..` and be a
   regular file or a folder (G-07: the release ships no links, so a symlink or hardlink member,
   whose target `tar -t` does not show, is refused). Any
   failure up to here removes the staging dir and the target dir when this run created it (a
   pre-existing empty dir is left empty).
6. Unpack (`tar --strip-components=1`), then `./install.sh --yes` with `--harness`, `--port`,
   `--wheels` passed through and `PYTHON` set to the Python found; its stdin is `/dev/null`. A
   failed install.sh keeps the folder and prints the re-run command. `--no-install` stops after
   the unpack.
7. Harness: `--harness` (claude, codex, gemini, dsh or a command template; the bare word `command`
   is refused by get.sh and install.sh with the template hint), else asked on `/dev/tty` when
   there is one (the script itself is on stdin), else the first of claude, codex, gemini, dsh on
   PATH, else install.sh's default (Claude Code). The choice is printed with where to change it.

Tests: `tests/release/test_get.py` serves a built dist/ over a local `http.server` in the GitHub
layout and runs the documented pipe against it (happy path with a full install, checksum
mismatch, malformed sum, missing release, non-empty dir, truncation, missing/old Python, root,
missing tools, harness asked on a pty and detected on PATH); `tests/e2e/one_line.sh` is the
fresh-install e2e installed by the one-liner.

`./install.sh [--port N] [--harness "<cmd>"] [--wheels DIR] [--from OLD] [--yes]`, run in the unpacked
folder (without `--yes` it asks on a terminal and refuses when stdin is not one):

1. Require `python3 >= 3.10` with `venv`; refuse to run as root; refuse if the folder path contains
   whitespace or is not writable.
2. `python3 -m venv .venv` (reused if it has a working pip) and `.venv/bin/pip install .`
   (`--wheels DIR` = offline install from pre-downloaded wheels: `pip install --no-index
   --find-links DIR --no-build-isolation .`, with the build backend taken from the venv when its
   setuptools can build alone (>= 70.1, or >= 61 + `wheel`), else from DIR; the recipe for DIR is
   `python3 -m pip download -d DIR <folder> setuptools wheel` with pip >= 23 (F-17: a `pip download` of the
   folder alone has no build backend, and build isolation found none offline). `--port` must be
   1024-65535 (F-32). A Python without `ensurepip` (Debian/Ubuntu without `python3-venv`) falls
   back to `virtualenv` when it is on PATH or importable; otherwise the installer stops and names
   the exact fix (`sudo apt install python3.X-venv`, the Fedora/Arch equivalents, or virtualenv).
3. Write `bin/konstant` (0755; the same text as the tracked file, so a deleted or edited wrapper
   is restored), create `var/` (`secrets/` 0700), `projects/`. With `--from`, first back up the old
   DB (`board backup` run against the old folder) and copy its `konstant.toml`, `var/` and
   `projects/`; refused when the old board runs or this folder already has a DB.
4. Write `konstant.toml` only if absent (port: `--port` or the first free port from 8470).
5. `konstant board init`: create/migrate the DB; mint tokens for roles missing a token file.
6. `konstant agents sync`.
7. `konstant doctor` and print the next steps (`bin/konstant board start`, open the harness here).

Idempotent: re-running keeps config, tokens and data, upgrades the venv, migrates the DB and
regenerates surfaces. Upgrade to a new release: unpack it next to the old one, then
`./install.sh --from <old folder>` copies `konstant.toml`, `var/` and `projects/` (board stopped,
DB backed up first). Uninstall: `bin/konstant board stop && rm -rf <folder>`.

`konstant doctor` checks: Python version, venv import of every dependency, config parse, `var/`
writable, DB schema version, file modes (`var/` 0700, the DB 0600; F-25), token files present +
0600 + dir 0700, the board host (WARN when `allow_remote` binds beyond loopback; F-24), board
`/health` (a pid file naming a process that is not this workspace's board is a stale-file WARN;
F-23), the jail (bubblewrap usable for agent-written tests and re-runs), stranded jobs
(when the board runs: `claimed` with no update for 6 h, `completed_unverified` waiting > 1 h for a
verdict),
`agents sync --check`, every configured harness resolvable on PATH (with its version), one `reach`
row per configured harness (what its own permission system enforces and each limit in words;
WARN when anything is partial or none, including a user-level leak that is present on this host),
for dsh the composed profile layers (`dsh --dump-config`, no model call; a foreign layer or
a composition it cannot read is a FAIL, since no dsh phase starts on it) and a workspace under
`/tmp`, and the Claude Code sandbox
prerequisites (bubblewrap + socat on Linux); it reports the role-separation mode (§5). Each line is
`PASS`, `WARN` (reduced capability: harness binary not on PATH, no sandbox), `FAIL` or `INFO` (the
board not running yet: install runs doctor before the board starts; the role-separation mode).
Exit 0 when no check FAILs; every WARN/FAIL names its fix. The WARN level exists so a fresh install
without Claude Code or without socat still completes.

Dependencies: `fastapi`, `uvicorn`, `pydantic>=2`, `PyYAML`, `tomli` (Python 3.10 only) and
`pytest` (the DoD check's `tests` rule runs `<venv python> -m pytest` over the tests a run wrote;
found by the fresh-install test, where every code run was UNMET with "No module named pytest").
The CLI client uses the standard library only, so `bin/konstant job …` stays fast.

## 11. Release process

1. `CHANGELOG.md` has a `## [V]` section; `src/konstant/__init__.py` carries V; the tree is clean
   (or `--worktree`: the current tracked + untracked-not-ignored files are archived through a
   temporary git index, so the fresh-install test can run before a commit).
2. `python -m konstant.release build --version 0.1.0 [--denylist PATH | --no-denylist] [--worktree]`:
   `git archive --prefix=konstant-0.1.0/ HEAD | gzip -n > dist/konstant-0.1.0.tar.gz` (export-ignore
   in `.gitattributes` removes the maintainer-only paths: `.github/`, the local `release/denylist*`
   and private planning notes a maintainer may keep under `docs/`; `release/build.py` refuses the
   notes and the denylist again after archiving), so the tarball equals the committed tree minus those.
3. Public-safety scan over every file in the tarball (`release/scan.py`):
   - `release/patterns.toml`: IPv4 addresses except loopback/unspecified/documentation ranges;
     email addresses except `example.com`/`example.org`/`noreply@`; token shapes (GitHub, cloud
     keys, chat-bot tokens, private-key headers, `token|secret|key = <long hex/base64>`); absolute
     home/server paths (`/home/<name>/`, `/srv/…`); internal ticket-reference shapes (configurable, e.g. `<PREFIX> #<digits>`).
   - denylist: one case-insensitive regex per line (a line that is not a valid regex is matched
     literally; `#` comments) from `release/denylist.local.txt` (git-ignored and export-ignored, so
     the names it lists are never published). A denylist finding is reported as `denylist:<line>`,
     never by the term. The build refuses without it unless `--no-denylist` is passed, and then
     prints and records `DENYLIST: SKIPPED`.
   - file names are scanned too (line 0); binary files (a NUL in the first 8 KiB) are counted, not
     decoded; a build-document path inside the tarball is a finding even if export-ignore missed it.
   - any finding → exit 1, the tarball is deleted, `dist/SCAN-REPORT.txt` lists file:line:pattern.
   - `python -m konstant.release scan --tree DIR [--denylist PATH]` runs the same scan over a tree
     (in a git work tree: what `git archive` would ship, export-ignore honoured).
4. `sha256sum` → `dist/konstant-0.1.0.tar.gz.sha256`, naming the bare file (`<hex>  konstant-0.1.0.tar.gz`)
   so `sha256sum -c` works next to a downloaded tarball (run it inside `dist/`);
   `dist/SCAN-REPORT.txt` records version, source tree id, sha256, scanned and binary file counts,
   pattern count, denylist term count and `RESULT: CLEAN`.
   `python -m konstant.release clidoc --write` regenerates `docs/CLI.md` from the parser (a test
   keeps them equal).
5. The one-line install assets (§10.1): `dist/get.sh` (the tarball's own `get.sh`, 0755),
   `dist/get.sh.sha256` and `dist/VERSION`; get.sh and VERSION are scanned like tarball members
   (a finding there deletes every output), and the report adds `ASSETS:` and `GET_SH_SHA256:`. A
   release without `get.sh` is refused. The GitHub release carries the tarball, its `.sha256`,
   `get.sh`, `get.sh.sha256` and `VERSION` as assets.
6. The fresh-install e2e (§12) and `tests/e2e/one_line.sh` run against the built assets before the
   tag `v0.1.0`.

## 12. CLI (`bin/konstant`)

Global: `--as ROLE`, `--json`, `--config PATH`; env `KONSTANT_HOME`. Exit 0 ok, 1 refused/failed,
2 usage or not found, plus the gate codes in §6.4.

| command | flags | does |
|---|---|---|
| `board init` | | create/migrate DB, mint missing tokens |
| `board serve` | `--host --port` | run uvicorn in the foreground; a non-loopback host needs `[board] allow_remote = true` |
| `board start` / `stop` / `status` | | background server with `var/board.pid`, log in `var/logs/board.log` |
| `board tokens` | `--rotate ROLE` | list roles/labels (never values); rotate; acts as owner unless `--as` says otherwise (F-27) |
| `board backup` | `--to PATH` | SQLite online backup into `var/backups/` |
| `project add SLUG` | `--name --path --init-git` | create project + root job (+ `projects/<slug>`) |
| `project list` | | |
| `job add TITLE` | `--project --parent --type --brief FILE|- --priority --after --approval --holdout-required` | brief must carry a `DoD:`/`Acceptance:` section; prints the DoD lint and `PROBE REFUSED:` warnings |
| `job list` | `--status --type --project --tree --self-attested --limit` | |
| `job show ID` | `--trail --json` | untruncated row (+ trail) |
| `job search WORDS` | `--open --project` | prior-work lookup over titles/briefs |
| `job claim ID` / `job block ID REASON` | | |
| `job note ID TEXT` | `--kind note|finding` | append to the trail |
| `job close ID` | `--evidence FILE` | parse `VERIFY_CMD:`/`VERIFY_EXIT=`/`PROBE:`/`COMMIT=` lines from FILE |
| `job review ID` | `--verdict FILE --done FILE` | docs-class close into `reviewed` (not by the requester, assignee or closer) |
| `job reopen ID REASON` / `job cancel ID REASON` | | |
| `job move ID --parent P` | `--reason` | |
| `job approve ID` | | owner |
| `job verdict ID PASS|FAIL|BLOCKED [REASON]` | | post a verdict by hand (verify roles; the closer cannot) — `konstant verify` is the normal path |
| `job lint FILE` | | DoD/PROBE lint (exit 1 when the DoD is missing or a PROBE would be refused) |
| `task classify TEXT` | | type + why |
| `task gate TEXT|-` | `--job --out --project --type --harness --cwd --session --file-job` | print gate block, write run record; bind a job (`[job:N]` tag, session, `--file-job`; §6.6) |
| `task run TEXT|-` | `--job --project --type --out --harness NAME|CMD --max-cycles --max-resumes` | phase runner + loop (§6.5); one run per project (exit 2 when another runs) |
| `task close RUN` | `--json` | interactive close-out (§6.6): MET -> claim if queued -> close -> verify |
| `task check RUN` | `--json --offline` | DoD check, gate exit codes; RUN = run dir under `var/runs/`, its record.json or its name (anything else: exit 2) |
| `task judge` | `--run RUN` or `--out DIR [--project P --base SHA]` | print `# JUDGED: <sha>` and record its args (exit 2 on an empty state) |
| `verify ID` / `verify --pending` | `--dry-run --no-rerun --json` | §7 (exit 0 PASS, 3 FAIL, 4 BLOCKED) |
| `holdout add ID` | `--file FILE` (repeatable) | lint + negative control + commitment; moves the files into the store (owner; §7.1; exit 1 refused, 2 no jail) |
| `holdout list ID` / `holdout check ID` / `holdout show ID HID` | `--control` (check) | commitments and states / commitment + parse (+ negative control) / one file from the store; check and show refused inside a task run |
| `agents sync` | `--check --harness NAME` | §8 (configured harnesses only) |
| `dsh APP [ARGS]` | `--project --dry-run` | start your dsh session (web, tui, headless) with konstant's two layers (§6.6); refused (exit 1) when the session would load a layer from outside the workspace |
| `agents list` | | types, agents, skills, workflows |
| `doctor` | | §10 |
| `version` | | |

## 13. Configuration (`konstant.toml`, defaults shown)

```toml
[board]
host = "127.0.0.1"             # a non-loopback host is refused unless allow_remote = true
port = 8470                    # 1-65535
allow_remote = false           # the board speaks plain HTTP with bearer tokens
db = "var/board.db"

[board.policy]
verify_roles = ["verifier", "owner"]
review_roles = ["owner", "orchestrator", "verifier"]   # never the job's requester/assignee/closer
reopen_roles = ["owner", "orchestrator"]
approve_roles = ["owner"]
evidence = "strict"            # off | warn | strict
vacuity = "strict"
negative_control = "strict"
max_rounds = 3

[client]
default_role = "orchestrator"

[catalog]
path = ""                      # empty: <workspace>/catalog, else the source tree

[harness]
name = "claude"                # claude | codex | gemini | dsh | command (docs/HARNESSES.md)
model = ""                     # through the harness's own model key; "" = its default
command = "claude -p --permission-mode dontAsk --setting-sources project,local --strict-mcp-config --add-dir {workspace} --settings {workspace}/.claude/settings.json {prompt}"
                               # the claude default; changed = your template for any name
stdin = false                  # only for your own template (adapters choose for themselves)
timeout_s = 3600
max_parallel = 2
env = {}

[harness.endpoint]             # a local OpenAI-compatible server, for codex and dsh
base_url = ""
api_key_env = ""

[harness.types]                # [harness.types.<type>] name / model / command per task type

[permissions]                  # the reach of a harness session (generated .claude/settings.json)
allow = ["Bash(pytest *)", "Bash(python -m pytest *)", "Bash(python3 -m pytest *)"]
                               # extra Claude Code permission rules: add your test runner
                               # ("Bash(npm test *)"), "WebFetch"/"WebSearch" for research phases;
                               # a rule granting a whole tool or a path outside the workspace is refused
sandbox = true                 # Claude Code Bash sandbox (writes confined to the workspace)

[gate]
max_cycles = 3
max_resumes = 3
test_cmd = "auto"
cleanup = "warn"               # warn | fail
verify_after_close = true
hygiene = { target = 250, hard = 400, tests = 600, grown = 600 }
jail = true                    # run agent-written tests, verifier re-runs, dsh phases and every phase of a holdout job in bubblewrap
file_job = false               # a gated dsh session files + claims a job for a typed task naming none

[holdout]                      # level-5 holdouts (§7.1); each default is one key
min_per_job = 2                # sealed scenarios a holdout job needs (at least one proof)
max_failed_rounds = 2          # failed holdout rounds before the set is worn and retired
run_timeout_s = 60             # one scenario run in the verifier's jail
store = "var/holdout"          # or an absolute path outside the workspace (a second OS user)

[verify]
rerun = true
rerun_timeout_s = 900
probe_timeout_s = 20
path_roots = ["."]
url_hosts = ["127.0.0.1", "localhost"]
```

An empty or missing role list means the default, never "nobody"; a malformed value stops the
board at start (a typo must not silently disarm a gate).

## 14. Test strategy

- **Unit (pytest):** every module; every DoD rule has a green fixture and a planted-bad fixture
  that must go red with its named reason (two-sided).
- **Board:** FastAPI `TestClient`, table-driven over (state, verb, role) → expected status code and
  resulting state, covering every row of §4.2 and the illegal ones; evidence contract incl. the
  vacuity corpus both ways ("ran 0 tests" refused, "0 failed" accepted); redaction; the closer
  cannot verify.
- **CLI:** subprocess tests against a real uvicorn on an ephemeral port in a temp workspace.
- **Gate:** classifier fixtures (small vs typed, every keyword, tag override, `?`-ending
  imperative typed); block budget; record shape; runner with a deterministic fake harness
  (`tests/fixtures/fake_harness.py`, behaviour chosen by the agent name in the prompt) covering
  MET, a FAIL back-edge, BLOCKED, the authorship refusal, the repeat-stop.
- **Verify:** every shape accepted with a safe operand and refused with an unsafe one; trivial
  regex refusal; settle table; path-root escape refused.
- **Catalog:** types.yaml schema + cross-references; `agents sync --check` red after an edit to a
  generated file, green after re-sync; 1:1 type ↔ agent invariant.
- **Release:** scan red on planted IP / email / token / denylisted word / home path; green on the
  clean tree; tarball excludes the maintainer-only paths.
- **E2E fresh install (`tests/e2e/fresh_install.sh`):** build the tarball → unpack into a new temp
  dir → `./install.sh --yes --port <free> --harness "python3 <fixtures>/fake_harness.py {prompt_file}"`
  → `doctor` → `board start` → `project add demo --init-git` → `job add` → `job claim` →
  `task run --job` (fake harness writes code, tests, verdicts, DONE.md) → `task check` exit 0 →
  job `completed_unverified` → `verify` PASS → job `verified` → a second job closed with a failing
  probe → `verify` FAIL → job `queued` → an offline install of a second copy from a `pip download`
  wheel dir with pip's network blocked (skipped, and said so, when no index is reachable to make
  the dir) → `board stop` → `rm -rf`. Every step asserts output; the transcript is the release
  check.
- **Harnesses (`tests/harness/`):** every adapter's default argv against a golden file
  (`tests/fixtures/golden/harness/`), the generated dsh patch / Gemini settings + policy and the
  AGENTS.md of a workspace without Claude Code (golden), the permission mapping both ways
  (codex profile, gemini policy, dsh patch; the real `codex sandbox` with konstant's profile when
  codex is installed), per-harness `agents sync --check`, doctor detection and reach rows, a
  planted foreign dsh layer, and the runner with per-type adapters (fake `dsh`/`codex` binaries)
  keeping the worker role and the F-05 reaper guarantee.
- **dsh session:** `tests/harness/dsh_gate/plugin.test.mjs` (node:test on the vendored
  bundle: gate, loop outcomes, repeat-stop, cap, verifier hand-off, leaves, child env, UNBOUND),
  `tests/harness/test_dsh_gate.py` (bundle present and built from the current source, rebuilt
  byte for byte when esbuild is there, sync surfaces + golden, the CLI the plugin calls,
  `konstant dsh --dry-run`), `tests/harness/test_dsh_jail.py` (a dsh phase cannot read the
  privileged tokens; red without the jail), and the live `tests/e2e/dsh_session.sh` (a fresh
  install, one dsh session on a local model, the job walked to `verified`).
- **Review fixes (`tests/review/`):** one red-then-green test per finding of the two security
  reviews (`test_F<nn>_...`, `test_G<nn>_...`; CONCEPTS "Security reviews"), written from the
  review's reproduction; the fake harness carries the reviews' adversarial modes (`declined`,
  `daemon`, `catalog`, `broken`).
- **Holdouts (`tests/holdout/`):** every lint rule, the negative control, the leak scan and the
  settle extension `_red`/`_green`; the sealed-store reach of the jail and every adapter, red when
  `machinery.SEALED` is emptied; the board's claim guard, PASS guard, burn and exposure budget;
  the CLI; and holdout jobs run through the real dsh adapter (stub dsh + the fake harness's
  `peek`, `overfit` and `leak` modes) to `verify`.
- **CI:** GitHub Actions on Ubuntu, Python 3.10 and 3.12: unit + board + gate + e2e.
