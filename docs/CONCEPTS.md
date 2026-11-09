# Concepts

konstant separates three things that agent setups usually mix: doing the work (a model), deciding
whether it is done (code that reads artifacts), and confirming it (a separate verifier). This page
explains the parts and how they connect. The full specification is [DESIGN.md](DESIGN.md).

## Workspace

The unpacked release folder is the workspace. `install.sh` turns it into one, and everything
konstant writes stays inside it:

```
bin/konstant               CLI wrapper (this folder's .venv, KONSTANT_HOME = this folder)
konstant.toml              local config (board port, harness command, permissions, policy)
var/board.db               the board (SQLite, WAL)
var/secrets/<role>.token   one token per role, 0600 in a 0700 dir (only sha256 in the DB)
var/runs/<stamp>-<slug>/   task-run records: record.json, phases/*.json + logs
var/logs/ var/backups/     board log, `board backup` copies
projects/<slug>/           your projects (git repositories)
memory/                    the memory vault: Markdown notes, its own git repository ("Memory")
catalog/                   the source of task types, agents, skills, workflows
.claude/ CLAUDE.md AGENTS.md   generated from catalog/ by `konstant agents sync`
```

Commands find the workspace from `KONSTANT_HOME`, `--config`, or the nearest parent folder with a
`konstant.toml`.

## Board

The board is a FastAPI server over SQLite that binds to `127.0.0.1`. It holds **projects**, each
with a root job, and **jobs**, at most two levels below the root: a job and its children. Every job
carries a brief with a required `DoD:` section, a type, a status and a trail of notes, findings and
verdicts. The web view at the board URL is read-only.

Job states: `queued → claimed → completed_unverified → verified`, with `blocked`,
`waiting_approval` (when `--approval` is set), `reviewed` (docs-class work closed by review) and
`cancelled`. `verified` and `reviewed` are terminal. A verifier `FAIL` sends the job back to
`queued` with the findings, or to `blocked` after `[board.policy] max_rounds`. An illegal move
answers 409 naming the current state. A role refusal answers 403 naming the roles that may act.

**Evidence contract.** `job close --evidence FILE` reads `VERIFY_CMD:`, `VERIFY_EXIT=`, `PROBE:`,
`COMMIT=` and `DOCS:` lines from the file. The board refuses the close when the check did not exit
0, or when the check is a no-op that cannot fail (`true`, `exit 0`, a bare `echo`). It also refuses output that measured nothing, such as "ran 0 tests" or "collected 0 items",
unless a non-zero count of things was checked. Optionally, a `CONTROL_CMD:` negative control must
have failed.

## Roles and tokens

There are five roles: `owner`, `orchestrator` (the default for the CLI), `worker`, `verifier` and
`viewer`. `board init` mints one random token per role. Pick a role with `--as ROLE`. Only
`verifier` and `owner` can post a verdict, and **the identity that closed a job can never verify
it**. The other terminal state works the same way: a review-type job is closed by `job review`
from an identity that neither filed, claimed nor closed it (by default the owner or the verifier
review the orchestrator's jobs).

For the dark factory (level 5) `board init` also mints five **identities**: tokens with their own
label - `planner`, `dod-reviewer`, `scenario` and `researcher` (role worker) and `factory` (role
orchestrator; `researcher` is the label konstant stores the closed web researcher's summary under,
"Triage").
`--as LABEL` acts as one; `board tokens --rotate ROLE --label LABEL` replaces one. The board
compares labels: a job's requester never approves its own DoD, and the identity that reviewed a
job's DoD or sealed its holdouts never claims or closes it, the planner of a goal job never
claims or closes it, and none of the five identities claims or closes work at all (the producer
and verifying phases act as `worker`). One model may play every one of these roles: the
separation is the identity, what each phase is shown, and the jail's file isolation.

On one machine, role separation is procedural:

- Harness phases run with `KONSTANT_IN_TASK=1` and act as `worker`; the CLI refuses every other
  token under it (`--as orchestrator|verifier|owner`). A worker closes only jobs it filed or
  claimed.
- The generated Claude Code settings deny the verifier and owner verbs inside a session, and
  `--as owner|verifier` anywhere on a konstant command line.
- For real separation, run `konstant verify` as a second OS user that cannot read the
  orchestrator and worker tokens. In that mode the verifier never executes the closer's
  `VERIFY_CMD`, only a `VERIFY_CMD:` line of the DoD. `konstant doctor` reports which mode is in
  effect. Read the limits below before relying on either mode.

## Task types and agents

`catalog/types.yaml` is the one source for task types, their agents, phases, verdict files, skills
and classifier vocabulary. The board, the gate, the check and the generator all read it. There are
nine types, each with exactly one agent:

| type | agent | phases in order (a verifying phase writes the named verdict file) |
|---|---|---|
| code / frontend / infra | coder / frontend / infra | architect (plan) → producer → tester `TEST-verdict.md` → reviewer `REVIEW-verdict.md` → architect `ARCH-verdict.md` |
| test | tester | architect → tester `TEST-verdict.md` → reviewer `REVIEW-verdict.md` → architect `ARCH-verdict.md` |
| security | security | (architect) → security → reviewer `REVIEW-verdict.md` → (architect `ARCH-verdict.md`) |
| review | reviewer | (architect) → reviewer → security → tester `TEST-verdict.md` → (architect `ARCH-verdict.md`) |
| docs / research / design | writer / researcher / architect | producer → reviewer `REVIEW-verdict.md` |

Phases in parentheses run only when the run changed a project file (read-only types). Every run
ends with the `orchestrator` close-out, which writes DONE.md and CYCLES.md.

Level 5 adds a tenth type, `intake` (agent `planner`: planner → reviewer `DOD-verdict.md`, acting
as the `planner` and `dod-reviewer` identities). It is reachable only through `bin/konstant intake`
("Goals and intake" below): the classifier and a `[type:intake]` tag never pick it, and it is never
a board job. A second role agent besides the orchestrator, `scenario-writer`, writes holdouts.

`bin/konstant agents list` prints the exact table from your catalog. The `orchestrator` profile
drives intake and the close-out. Each agent profile in `.claude/agents/` is composed from its role,
the shared doctrine, the deliverable contract of its type and the skills of its type.

## Task gate

`konstant task classify "<task>"` maps a task to a type with no model call. An explicit
`[type:x]` tag wins. A question ("what ...?", "how ...?") is `small`, which runs inline with no
gate, unless it is a request ("can you implement ...?"). A keyword plus a deliverable signal, or an
imperative ("add retries to the client"), picks a type, before any chat opener is considered: "ok,
implement X" is gated. A message that is only a chat opener is `small`. Anything else that asks
for a deliverable becomes `code`. A small task runs in the project dir when `--project` is given
and refuses `--job` (an ungated run never closes a job).

`konstant task gate "<task>"` prints a short block (the phases, the verdict files, the OUT
directory, the judge command and the DONE.md shape) and writes a run record under `var/runs/`. An
interactive session then runs one subagent per phase.

`konstant task run "<task>"` is the enforcing mode. konstant itself drives the phases, with one
headless harness run per phase. It composes the agent profiles once, when the run starts (a phase
that edits `catalog/` cannot change what a later phase is told). It snapshots OUT around each run,
records which phase created or changed which file and the sha256 of each verdict file it left, and
kills every process a phase left running before the next phase starts (Linux). A verifying phase
that says FAIL sends the work back to the producer, up to 3 cycles. `[harness] max_parallel = 1`
runs every phase alone, for strict per-phase attribution. One run per project at a time.

## Triage

Before anything plans a task, konstant triages it, by code, in the order the owner's orchestrator
asks: what type of task is this, how big is it, is it new or a continuation, what has been done
before, what can be reused, and does it need research first.

**Five size tiers** sit on top of the type (`konstant task classify` prints both, each with its
reason; `konstant/triage/tiers.py`):

| tier | means | chosen when |
|---|---|---|
| `inline` | the orchestrator answers in its own session, no gate | the classifier says `small` |
| `agent` | one typed run with its workflow | one deliverable |
| `fanout` | several typed runs in parallel, one per independent part | at least `[triage] fanout_min` (3) parts: list items, distinct file paths, or a count such as "12 modules", counted before the DoD section |
| `max` | as many parallel typed runs as the endpoint allows | a whole-scope phrase ("the entire codebase", "every module", "all services") or more parts than the cap |
| `factory` | a long-running goal: goal -> intake -> jobs -> holdouts -> ship, until the goal's acceptance is met or each job used its `max_attempts` | a long-running phrase ("for a week", "until all tests pass", "keep running") AND a mechanical acceptance (PROBE or VERIFY_CMD rows, a DoD section, "until the tests pass") AND a type the factory can ship |

`max` is never unbounded. `[harness] max_concurrency` is the number of requests your endpoint
serves at once (its slots); a typed run runs up to `[harness] max_parallel` phases at once, so the
cap is `max_concurrency // max_parallel` typed runs (at least one). Unset, konstant does not know
the slots and runs one at a time. More agents than slots do not finish sooner: they evict each
other's prompt cache and every one of them gets slower. The runner also never runs more parallel
phases than `max_concurrency`. Override any tier with a tag: `[tier:agent]`, `[tier:max]`, ...
(`[tier:factory]` on a run bound to one job becomes `agent`: a job is one unit of work).

**Which tasks suit the factory.** A goal with a measurable end state and a mechanical acceptance:
a library that must pass a suite, a CLI whose commands a probe can run, a port that must reach
parity with the original's tests. Not: open-ended taste work ("make it nicer"), a goal nobody can
check without a person, documents and reviews (their deliverable is a verdict or prose, not
something the verifier can run), and `infra` (it ships only by an owner decision). A long-running
request that fails these rules gets a size tier instead, and the tier says why it is not a
factory task. `konstant task run` refuses a factory task with the way to file it as a goal; the
gate block tells an orchestrating session the same.

`fanout` and `max` are carried out by the orchestrating session: it splits the work into the
parts the intake card names and runs at most the cap at once, one `konstant task gate` per part
(skill `fan-out`). `konstant task run` works a fanout task as one typed run and says so.

**The intake card** (`konstant/triage/card.py`) is the first step of every non-inline task, done
by code before any model plans it. It holds:

- the type and tier, each with its reason;
- **new or continuation**: a run bound to an existing job continues it; an open job or an active
  goal that shares the task's file paths or keywords makes it a continuation; otherwise it is new;
- **prior work**: board jobs and goals that share paths or keywords (closed ones are similar work
  done before) and a memory recall over the shared pool, lessons of verified jobs first;
- **reuse candidates**: files the task names that exist in the project, project files whose name
  matches a keyword, catalog skills that match;
- **research required**: a new task with nothing similar on the board or in memory.

The card is printed after the gate block, put into every phase prompt (not the close-out), kept in
the run record, and recorded on the job (`job show --json` lists `intake_cards`; the trail gets a
one-line note). An unreachable board is a warning, as for every gate read: the card says the
lookup was not done, and research is not required on a lookup that never happened.

**The researcher.** When the card requires research, the plan starts with konstant's closed
researcher: the `researcher` agent as the `researcher` identity, run before the first phase by the
runner (an interactive session runs `konstant task research <run>`; the DoD rule `research` is
UNMET until it ran). It always runs inside konstant's jail, whatever the confinement profile, with
the network and nothing else: `$HOME` masked, no credential file or variable, no ssh agent, no
docker socket, no token, the workspace's projects, run records and board DB masked, writable only
its own dir in the research store `var/research/<run>/`. No producer can read that store (it is in
the integrity core). Pages it fetches are untrusted data. It writes a summary of rows
(`SOURCE | S1 | <url> | LICENCE <id> | ...`, `FINDING | <claim> | S1`, `REUSE | ... | S1`, or
`NOTHING-FOUND | <why>`); konstant keeps only those rows, refuses an uncited finding, a source
without an http(s) URL or a licence, and any line shaped like an instruction to an agent (an
injected page), renders the rest itself and stores it in the shared memory pool as `researcher`.
Producers get that rendering, framed as data, never the raw pages. Without a working jail it does
not run (recorded as `unavailable`, a warning): it never runs open. `[triage] research = "off"`
drops the requirement (`doctor` WARNs).

**Copied code needs a recorded compatible licence.** A run that copies code from elsewhere records
each copy as `COPIED | <path> | <source> | <SPDX id>` in DONE.md or `OUT/LICENSES.md`. The DoD rule
`licence` refuses a row whose licence is unknown or incompatible with the project's own (read from
LICENSE, pyproject.toml, package.json or Cargo.toml: permissive sources go anywhere except
Apache-2.0 into GPL-2.0-only; copyleft only into a project its terms allow; unknown never), and a
changed code file whose added lines show an outside source (a "copied / adapted / ported from"
note, a foreign `SPDX-License-Identifier:`, a URL of the run's research sources) without a row.
DECLINED never excuses it. konstant checks declarations and provenance marks: a silent copy that
leaves no mark is not detected, and the table is a conservative rule of thumb, not legal advice.

## DoD check and loop

`konstant task check <run>` reads only files (the run's OUT directory, the project's git state and,
for the `verified` rule and DECLINED rows, the board). It judges only run dirs under the
workspace's `var/runs/`, and takes the phases, verdict words, DONE.md shape and `[gate]` settings
(the test command above all) from the workspace's catalog and `konstant.toml`, never from the run
record. Its exit codes are 0 MET, 3 UNMET (one reason per line), 4 BLOCKED (honestly unverifiable)
and 5 for a failure of the check itself. The rules:

- **verdicts / phases**: each verifying phase left a fresh verdict file ending in one
  `# VERDICT: <word>` line, and the newest cycle decides.
- **judged**: a PASS verdict carries `# JUDGED: <sha>` from `konstant task judge`. A content hash
  of OUT plus the project diff that changes after judging is caught.
- **authorship**: in runner mode, a verdict file must have been written by the phase it names,
  and its content must still be what that phase left. A producer that writes its own verdict, or
  anything that changes a verdict after its phase ended, is refused, and no resume can undo that.
- **done / absence / surfaces**: DONE.md rows `ID | claim | STATUS | evidence` with real evidence,
  at least one PASS row, a proof-of-absence row and the surfaces a build touched. A run bound to a
  job answers every row of the job's DoD as `DoD-<n>` (PASS or BLOCKED, never N/A).
- **tests / exercise**: the tests pass: by default `pytest` over `test_*.py` under OUT AND the
  project's own test suite when the project has Python test files (a change that breaks an
  untouched test is UNMET); for Python the tests actually enter the code in OUT. Other languages:
  set `[gate] test_cmd` (workspace-wide).
- **last mile / hygiene / cleanup**: no stray untracked files, no TODO/FIXME markers added, no
  oversized source file without a reason line, and a `CLEANUP:` line.
- **research**: when the intake card required research, konstant's closed researcher ran for
  this run ("Triage").
- **licence**: copied code carries a `COPIED` row with a compatible licence ("Triage").
- **verified**: the run's job, once closed, has a `konstant verify` verdict.

A DONE.md row `DECLINED | <claim> | job <id>` excuses a finding only when the claim quotes it and
job `<id>` carries an owner note `DECLINED: <the same claim>` (`bin/konstant --as owner job note
<id> "DECLINED: ..."`), read from a reachable board. It never excuses the verdicts, phases,
judged, tests, verified, authorship, holdouts, research or licence rules: what the verifiers, the tests and the
holdouts say is not waived by text an agent writes. A producer that believes a holdout contradicts
the DoD writes `DISPUTE | H<n> | <why>`: the run stops BLOCKED and the owner decides.

On UNMET the runner resumes the phase that owns the first reason, up to `[gate] max_resumes`
times. It stops early when the same reason comes back unchanged. BLOCKED is never resumed.

## Verifier

`konstant verify <job>` re-checks a `completed_unverified` job with the verifier token:

1. It collects `PROBE: <command> => <regex>` lines from the job's DoD and from the closer's
   evidence.
2. It runs each probe without a shell, and only if it matches an allowlisted read-only shape:
   `test -e|-f|-d`, `ls -ld`, `stat -c`, `sha256sum`, `grep -c`, read-only git plumbing
   (`git -C TREE rev-parse|log -1|branch -r --contains|blob-sha256`, with system and global git
   config off and no hooks or transports; `status` and `ls-remote` are not allowed because a
   repo's own config could make them run a command), `curl -s` to loopback hosts,
   `systemctl is-active|is-enabled|show`, `docker inspect -f`, `sqlite3 -readonly ... SELECT`,
   `<binary> --version` and `konstant job show ID --json`. Paths must resolve under
   `[verify] path_roots` and the project paths, never into the workspace's `var/`, and the
   resolved path is what runs. A regex that matches anything is refused.
3. It re-runs a verify command in the project directory with a scrubbed environment: the DoD's
   `VERIFY_CMD:` line when it has one, otherwise the closer's `VERIFY_CMD` (procedural mode only).
   The re-run runs in konstant's jail when bubblewrap works (tokens and the credential locations
   listed under "Security model and limits" masked, writes only to the project dir); otherwise
   with your user's rights. Turn it off with `[verify] rerun =
   false` or `--no-rerun`.
4. It settles the result. PASS needs at least one `PROBE:` from the job's DoD that matched, and
   nothing that failed: the re-run and the closer's own probes replay the closer's claim, so they
   can fail a job but never pass it alone. FAIL means a contradiction or a failing re-run. BLOCKED
   means nothing independent could be verified. Then it posts the verdict.

`--dry-run` reads and prints without writing anything. `--pending` verifies every job that waits.

## Holdouts

A holdout is a black-box acceptance scenario for one job that the agent doing the work never
sees (level 5, [LEVEL5.md](LEVEL5.md) section 3). You write it before the job is claimed, in a
file OUTSIDE the workspace:

```
SCENARIO: greet uses the caller's name
KIND: proof
RUN: python3 -c "from greeter import greet; print(greet('Ada'))"
EXPECT_EXIT: 0
EXPECT_OUT: hello Ada
HINT: names other than the default are used verbatim
```

`bin/konstant holdout add JOB --file h1.scenario --file h2.scenario` checks the files (every key
present; `RUN` drives the product itself, not a test runner, and runs without a shell; the
expectation is not trivial and does not appear in the job's brief or DoD; the hint gives nothing
away; at least `[holdout] min_per_job` scenarios, one of them `proof`), runs each once on the
project's current commit (a `proof` that already passes there checks nothing: `VACUOUS`; a
`regression` must pass), and then MOVES the files into the sealed store `var/holdout/`. The board
keeps only a hash of each file. The job is now `holdout_required`: it cannot be claimed without a
sealed set.

The store is masked inside konstant's jail and read-denied by every harness adapter, and a job
with holdouts runs in **factory mode**: every phase inside konstant's jail on any harness (claude,
codex, gemini, dsh or your own command), reading only its own identity's token; without a working
jail the run exits 2 `holdouts need a confined phase`. The first claim gives the job its own
**clone** of the project, `projects/<slug>@<job>`, made from the project's current commit; the
phases work and commit there, the verifier judges it (a DoD probe may say `{workdir}/file`), and
the project itself (the target) stays read-only to every phase. Claude Code's own sandbox runs
nested inside the jail when it can (bubblewrap, socat, a private `/tmp`); otherwise it is switched
off for the phase and the jail is the boundary - `doctor` says which. The producer is told only
that holdouts exist and how many.
`konstant verify` then checks the store against the hashes, scans for a leaked canary or a copied
expectation, materialises the exact commit the job closed with, and runs every scenario there
without network. A failure shows only `holdout H1 failed (hint: ...)`; PASS needs everything a
level-4 PASS needs **and** every holdout passed. Repeated failures wear a set out (it is retired
and a fresh one must be sealed); a leaked canary burns it. `holdout list` shows ids, kinds, hashes
and states, never content; `holdout show` prints one file and is refused inside a task run.

## Goals and intake

At level 5 you say what you want; konstant turns it into jobs ([LEVEL5.md](LEVEL5.md) section 4).
A **goal** is the goal text, its project and its limits (only `max_attempts`, attempts per job, is
required; default 3), as a TOML file:

```toml
[goal]
id = "greeter"
project = "greeter"
text = "A small greeting library: greet(name) and a CLI `greet NAME`."
[limits]
max_attempts = 3
```

`bin/konstant --as owner goal add goal.toml` files it (a copy goes to `var/factory/goals/`, which
no phase can write, with its sha256 on the board; editing your file later changes nothing). Or you
just ask your orchestrator in the dsh chat ([DSH.md](DSH.md) "The chat is the intake"): it
proposes the goal in one line, and your next message `yes` files it.

The factory loop then takes it in (`bin/konstant factory start`; by hand: `bin/konstant intake
greeter`), every phase in konstant's jail:

1. a **planner** phase (identity `planner`) writes `BACKLOG.md` and one brief per job, each with a
   DoD whose rows `PROBE:` lines settle (paths of the result as `{workdir}/...`);
2. a **DoD review** phase (the reviewer, identity `dod-reviewer`) writes `DOD-verdict.md` with one
   SHIP/FIX line per job; FIX sends the planner back;
3. konstant **files** the jobs only if every brief passes `job lint` with no flag and carries a
   PROBE, the types are real and the `after:` order is sound (else exit 3, nothing filed); each job
   is filed by the planner identity, its DoD review posted by the dod-reviewer identity, and
   approved by the `factory` identity;
4. the **scenario writer** (identity `scenario`) writes each job's holdouts from the goal, the
   brief and a read-only view of the project, in a jail where it sees no job clone, no run record,
   no board and no token; konstant lints them, runs them on the current commit and seals them.

The order is the point: DoD, review and holdouts exist before any producer runs, each from a
different identity. A job whose holdout authoring fails twice is reported `BLOCKED` and waits
(its claim needs sealed holdouts).

## Ship

At level 5 a verified job ships itself ([LEVEL5.md](LEVEL5.md) section 5; `bin/konstant ship
JOB`, run by the `factory` identity; the factory loop calls it, see "Factory"). It ships only
the exact commit the verifier passed, checks the shipped state, and undoes the ship when that
state fails.

| target | ship | rollback |
|---|---|---|
| `github` (opt-in; this owner's default) | push `konstant/ship-<n>`, `gh pr create`, `gh pr merge --merge --match-head-commit <commit>`, fetch the merge back | a commit with the pre-ship tree on top, pushed as `konstant/rollback-<n>` and merged through its own pull request |
| `branch` (the default) | `update-ref` of the project's branch, compare-and-swap | the same revert commit, CAS again |
| `apply` | the commit's tree into `[ship] apply_dir`, the old one kept as `.prev` | swap `.prev` back |
| `command` | your `ship_cmd` (`{commit}`, `{branch}`, `{job}`) | your `rollback_cmd` (required) |

Never a force-push, a reset or a branch delete: the shipped commit stays in the history, and a
rollback is a new commit whose tree equals the tree before the ship.

**What ships is what was verified.** konstant does not push from, or run git in, the job clone a
phase worked in (its `.git` could carry replace refs, grafts, a planted config or hooks). It copies
the commit object by object into its own repository (`var/factory/ship/<project>.git`), hashing
every object itself: content that does not hash to its id refuses the ship. Because a git id is its
content, the commit that ships is exactly the one the holdouts ran on.

**The guard**, checked by konstant and again by the board: the job is verified, its latest
verification carries every sealed holdout passed (the set's commitment digest, no LEAK), and the
holdouts, the evidence `COMMIT=` and the ship name the same commit; the target is still where the
job's clone started (else `target moved`); the catalog matches its manifest; shipping is not
halted; one ship at a time; a job ships once. A job without holdouts never ships.

**Owner decisions** (escalation `DECISION`; nothing moves until `bin/konstant --as owner ship JOB
--approve-decision`): a job type in `[ship] decision_types` (default `["infra"]`); a diff touching
`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.claude/`, `.agents/`, `.dsh/`, `.gemini/`,
`.github/workflows/`, `.github/actions/`, `sitecustomize.py`, `usercustomize.py`, a `*.pth` or a
`conftest.py` outside a test dir; only regression holdouts; a target that moved; and, for `github`
and `command`, a **secret scan** finding (the release scanner's patterns plus a denylist over the
added lines and paths; the finding names the path, never the text).

**After the ship** konstant checks the new tip: the goal's `post_probes` and the job's own DoD
probes (`{workdir}` = the target), the project's tests and every holdout of every job shipped so
far, in the jail on the tip it materialised itself. Any failure, or a check that cannot run, rolls
the ship back; the job stays `verified` (it was true of the clone) and a **follow-up job** is
filed by code: the same brief and holdouts plus the failed post-ship probe as a `PROBE:` row. A
rollback that fails halts ALL shipping (`factory status` says `halted`) until `bin/konstant --as
owner factory resume-shipping`; nothing is retried or forced.

**Credentials.** Only the ship step uses your `gh` and git push credentials: konstant's own pinned
`gh` (`[ship] gh`, an absolute path, else gh in the root-owned system dirs) and its pinned git,
with an environment it builds itself (your `HOME` for `~/.config/gh`, `GH_TOKEN`/`GITHUB_TOKEN`
when set, the ssh agent), in the factory process, never in a phase. Under the closed profile no
phase can read them (`~/.config/gh`, `~/.git-credentials` and the token variables are masked or
dropped). Under the open profile a phase holds your environment and host by your choice; the
ship's push does not use anything a phase set, but an open phase could push with your
credentials itself (that is the open profile's stated risk, not something the ship step adds).

## Factory

The factory loop is the dark factory itself ([LEVEL5.md](LEVEL5.md) section 6): `bin/konstant
factory start` (or `factory run` in the foreground, or the systemd unit `factory install-unit`
writes) runs one loop per workspace that takes each goal in, attempts its jobs one project at a
time, lets the verifier judge them, ships what passed and starts the next, for as long as there is
work, days or weeks. No model decides anything in it: it reads the board and runs konstant's own
verbs (`intake`, `holdout author`, `task run --job`, `verify`, `ship`).

**Budgets.** A job gets `max_attempts` task runs (default 3, the only required limit); after the
third it is `blocked` and you hear about it once. A goal may also set `max_task_runs`,
`wall_clock`, `max_tokens` and `max_cost_usd`: when one is reached the goal pauses
(`BUDGET_STOP`). konstant charges every attempt before it starts and measures the rest from the
runs; a token or cost limit on a harness that does not report usage is refused before the start,
never guessed. To grant more, acknowledge the escalation (`factory ack ID`) and resume the goal or
reopen the job: an acknowledged escalation opens a fresh window for the limit that raised it.

**You are told only what needs you**: `BLOCKED`, `DECISION`, `BUDGET_STOP`, `LEAK`,
`ROLLBACK_FAILED`, `HALTED`, each once per goal, job and kind until you acknowledge it. Outcomes
(`SHIPPED`, `ROLLED_BACK`, `GOAL_DONE`) are on the status view and in `var/factory/events.jsonl`,
never pushed. `[notify] kind` says where: `stdout`, `file` (`var/factory/notify.log`), `webhook`
(a POST of the event and its one-line redacted reason, nothing else) or `chat` (into the
orchestrator session the goal came from, shown at your next message there; [DSH.md](DSH.md)). A
notifier that cannot deliver **halts the factory**: the event waits in `var/factory/spool/`, and
`bin/konstant --as owner factory resume` delivers it and lets the factory run again. A dark
factory you cannot hear from does not keep working.

**Stopping and restarting.** `factory stop` sets the kill switch (`var/factory/STOP`): the loop
starts nothing new, lets its running steps finish and exits; no factory starts while the switch is
set (`factory resume` clears it). Every step is a board transition or a konstant verb with its own
guards, so a factory that was killed (or a host that went down) resumes from the board: a claimed
job gets its next attempt, a closed job without a verdict is verified, and a ship cut off half way
is reconciled by comparing the target with the ship's record (never left blocking; when konstant
cannot tell what happened, shipping halts for you). A loop that makes no progress while work is
ready for `[factory] stall_after_s` tells you so (`factory stalled`), and its heartbeat shows on the
board's Factory tab and in `doctor` (stale after three ticks).

**The Factory tab** of the board (read-only) shows the loop, each goal's budget used and limit,
its jobs by state with attempts left, ships, escalations and the last events; `bin/konstant factory
status --json` prints the same. Holdouts appear only as counts.

## Memory

konstant has a built-in memory that every harness uses the same way: notes earlier jobs and
sessions left (decisions, pitfalls, how something works), recalled before new work starts.

- **The vault is the source of truth**: `memory/` in the workspace, plain Markdown notes with YAML
  frontmatter, `[[wikilinks]]` and `#tags`, so you can open the folder in Obsidian (or any editor)
  and read or search it as it is. Two pools, `shared/` and `sealed/` (below), with one folder
  per writer inside (`shared/worker/`, `shared/planner/`, `sealed/verifier/`, ...).
  It is its own git repository (`memory/.git`, never mixed with the workspace's or a project's
  history): every write konstant makes is one commit, authored by the identity that wrote it.
- **The index is a cache**: `var/memory/index.db`, SQLite full-text search from Python's
  standard library, rebuilt from the vault at any time (`bin/konstant memory reindex`). Recall
  is lexical unless you name a LOCAL OpenAI-compatible embedding endpoint; then it is hybrid
  (text match + vector similarity), and when the endpoint does not answer it falls back to
  lexical and says so:

  ```toml
  [memory]
  embed_endpoint = "http://127.0.0.1:8000/v1"   # vLLM, llama.cpp --embeddings, Ollama
  embed_model = "<the name it serves>"
  # engine = "chroma"   # optional: vectors in a local Chroma collection
  #                     # (pip install 'konstant[chroma]' into .venv; about 0.5 GB)
  ```
- **One MCP server for every harness**: `bin/konstant mcp memory` (stdio) with three tools:
  `kb_recall` (search), `kb_store` (a short fact), `kb_note` (a named note with links and tags).
  `agents sync` wires it into Claude Code (`--mcp-config`, the tools allowed by name), Codex
  (`-c mcp_servers...`), Gemini CLI (`mcpServers` + policy rules) and dsh (an MCP client row in
  the patch); [HARNESSES.md](HARNESSES.md) has the details. Any other agent, or a shell, uses
  the CLI: `bin/konstant memory recall|store|note|list|show|log`.
- **The board's web view** has a read-only Memory tab: recent notes, search, one note.

Memory is a channel between jobs: agents learn from each other's notes, through one-way glass
(owner decision 2026-11-08), and the integrity core covers it:

- **One shared pool.** Every producing identity (the phases acting as `worker`: coder, tester,
  reviewer, researcher, ...; the planner and the DoD reviewer; the orchestrator, the factory, the
  owner) reads AND writes `shared/`: each agent recalls every earlier job's notes and lessons.
- **The sealed pool, behind one-way glass.** The scenario writer and the verifier READ the
  shared pool but write only `sealed/`, which no producer, planner, orchestrator or viewer token
  (and so not the web view) ever sees; it is inside the integrity core, like the holdout store.
  The owner reads both. The scenario writer's phase still holds no token: konstant exports what
  it may read into its drafts dir before the phase, its memory server recalls from that copy, and
  konstant stores the notes it wrote into the sealed pool afterwards.
- **Source and proof on every note.** A note lands in the folder of the identity whose token
  wrote it (the board takes it from the token, never from the request), with the job it was
  written for. Recall labels each note `verified job N`, `job N not verified (<status>)`, `no job`
  or `not written by konstant`, from the board's own records (never from the note's
  frontmatter), and ranks lessons of verified jobs first: a wrong lesson from a job that never
  passed is marked as such instead of spreading as truth.
- **No phase reads the vault directly.** `memory/` is on konstant's machinery list as both
  unwritable and unreadable (like the holdout store): the jail masks it and every harness's
  permission rules deny it, so a phase reaches memory only through the board, where the rules
  above apply.
- **Nothing sealed enters memory.** Every write is redacted like a board field (tokens, keys,
  `NAME=secret` assignments) and scanned against the sealed holdout store: a canary, a pasted
  scenario or a held-out literal of any sealed scenario is refused. A phase's refused write is
  written on its job's trail, and the verifier counts it as a LEAK (canary, scenario) or a
  LEAK-SUSPECT (literal) of that job.
- **Memory is never evidence.** Probes refuse paths into the vault and the memory routes, the
  board refuses a close whose `VERIFY_CMD` runs `konstant memory`, and the verifier's re-run and
  holdout runs see an empty `memory/`.
- **Attributed and reviewable.** Every write and every refusal is a row of the board's
  append-only `memory_writes` (who, what, which run and job); `bin/konstant memory log` lists
  them, and `git -C memory log` shows the same history.
- **Shared with your own tools or not** (`[confinement] memory_share`, open profile: on,
  closed: off). On: notes you add or edit in `memory/` yourself are recalled too. Off: phases
  recall only notes konstant wrote, byte for byte; a note changed outside konstant stops being
  served until it is stored again.

## Generated surfaces

`konstant agents sync` renders `catalog/` into `.claude/agents/<agent>.md`,
`.claude/skills/<skill>/SKILL.md` (26 skills plus one `workflow-<type>` skill per type, the
level-5 `intake` type included),
`.claude/settings.json`, `CLAUDE.md` and `AGENTS.md`. Generated files carry a header and are
overwritten on every sync. Edit `catalog/` instead. `agents sync --check` (also run by `doctor`)
names every drifted file.

## Permissions model

Headless phases are **workspace-scoped** (a design decision; the default `closed` confinement
profile, next section), whatever the harness; how that maps
onto Codex, Gemini CLI and DeepSeek Harness, and what each cannot enforce, is in
[HARNESSES.md](HARNESSES.md). For Claude Code (the default) the command is
`claude -p --permission-mode dontAsk --add-dir {workspace} --settings {workspace}/.claude/settings.json {prompt}`,
and the generated settings file defines the whole reach:

- **allow**: Read/Edit inside the workspace, the konstant verbs a phase needs (`job`,
  `task classify|gate|check|judge`, ...), local git verbs (`status`, `diff`, `add`, `commit`, ...;
  not `init`), and the rules in `[permissions] allow` (your test runners). Rules that grant a whole
  tool, reach outside the workspace or put a wildcard before the command are refused by
  `agents sync`.
- **deny** (deny wins over allow): edits to konstant's own machinery (`bin/`, `.venv/`, `src/`,
  `.claude/`, `catalog/`, `tests/`, `install.sh`, `pyproject.toml`, `konstant.toml`, the board DB,
  run records), edits to any `.git/` directory (a `.git/config` edit would turn `git status` into
  arbitrary execution), reading `var/secrets/`, the verbs of other roles (`verify`, `job verdict`,
  `job approve`, `task run`, `board`, `agents sync`) and `--as owner|verifier`.
- `--permission-mode dontAsk` denies everything that would otherwise prompt.
  `blockReadsOutsideWorkingDirectories` stops reads by the Read tool outside the workspace (not
  reads by a command), and `disableBypassPermissionsMode` prevents a session from skipping all of
  this. `--setting-sources project,local --strict-mcp-config` keep your user-level settings,
  hooks and MCP servers out of a phase.
- **sandbox** (`[permissions] sandbox = true`): Claude Code's Bash sandbox confines writes to the
  workspace and read-denies the usual credential locations (`~/.ssh`, `~/.aws`, ...). The allow list
  stays authoritative inside it (`autoAllowBashIfSandboxed = false`).

A live check (one `claude -p` run with this setup) ran an allowed `bin/konstant job list`, while
reading `/etc/hostname` with the Read tool, `cat /etc/hostname` and `touch /tmp/...` were each
denied.

## Confinement profiles

What a phase may see and do is ONE choice in `konstant.toml`, plus options that override it
(`konstant/confinement.py`; `./install.sh --confinement closed|open` and `get.sh` ask on a
terminal and write it for a new workspace):

```toml
[confinement]
profile = "closed"      # closed (the default) | open
integrity = "on"        # on | off (off: level 4 only, with profile = "open"; see below)
# any option of the table below overrides the profile, e.g.
# credentials = ["~/.ssh", "~/.config/myservice/token", "$GITHUB_TOKEN"]
# docker_socket = false
```

- **closed** (default, the 0.1.0 reach): a phase writes only inside its project (in factory mode
  its job clone) and OUT; the credential and agent homes konstant lists (below) are masked; no ssh
  agent, no docker socket; the credential variables konstant lists (`GITHUB_TOKEN`, `GH_TOKEN`,
  `AWS_*`, `VAULT_TOKEN`, ... in `machinery.CREDENTIAL_ENV`; never a harness's own API key) are
  not in its environment.
- **open**: a phase gets the host the way your own shell does: it reads and writes anywhere your
  user can, uses the network, ssh and your ssh agent, the docker socket, your credential files
  and variables. Use it when you trust your agents with your servers, as you would a colleague at
  your keyboard.

**The integrity core holds in every profile** (and always in factory mode): the sealed holdout
store, the memory vault's files and the research store are unreadable; every token but the phase's own identity's (and the read-only viewer's) is
unreadable; konstant's machinery (the catalog, the generated harness surfaces, `var/`
bookkeeping, the board DB with the job's verdict history, `.git` of the workspace) is not
writable; in factory mode the target repository and the other job clones are read-only too. This
protects the meaning of "verified", not the host: whatever a phase may do to your machine, it
cannot read the tests it is judged by, act as the verifier, or rewrite konstant's record of what
happened. Under the open profile every phase therefore runs in konstant's jail at level 4 too, as
a thin layer: the host root bound writable, with masks and read-only binds over only the
integrity core (claude, codex, gemini, dsh and `command` alike; without a working bubblewrap an
open level-4 phase gets only its harness's own rules, and `doctor` says so).

| option | closed | open | allows | risks |
|---|---|---|---|---|
| `network` | harness default | true | commands of a phase reach the network (beyond the harness's own model traffic) | exfiltration of anything the phase can read; downloads that run code |
| `home_read` | true | true | read your home folder outside the workspace (the credential locations stay masked unless `credentials` passes them) | private files (notes, other projects, browser data) reach the model |
| `home_write` | false | true | write anywhere in your home folder | a phase can plant code your own unjailed sessions run later (shell rc files, agent homes, ~/.local/bin) |
| `host_write` | false | true | write anywhere you can outside the workspace (implies home_write) | anything your user can change on this host, including other repositories |
| `extra_read` | `[]` | `[]` | read these paths even where the profile masks them | what is in them reaches the model |
| `extra_write` | `[]` | `[]` | write these paths | whatever later reads those paths trusts what a phase wrote |
| `credentials` | `[]` | `["*"]` | pass these credential files/folders (e.g. ~/.ssh, a token file) and $VARIABLES through; "*" = every location and variable konstant lists | the phase can act as you on every service those credentials reach |
| `ssh_agent` | false | true | use your ssh agent (SSH_AUTH_SOCK and its socket) | ssh to every server your agent's keys open, without seeing a key; an ssh login into THIS host leaves konstant's jail |
| `docker_socket` | false | true | use the docker daemon (its socket, DOCKER_HOST); never in factory mode | the docker socket is root on this host: a phase that uses it can read and change anything, the integrity core included (so factory mode never passes it) |
| `memory_share` | false | true | the memory vault is shared with your own tools: notes you add or edit in `memory/` yourself (an editor, Obsidian) are recalled by phases as well as the notes konstant wrote | anything that can write `memory/` outside konstant steers every later phase, unattributed; private notes you keep there reach the model |
| `host_agents` | false | false | the orchestrator session started by `konstant dsh` may run the host's own agent launchers (dsh, claude, codex, gemini) by name | a launcher that loads your personal agent setup (its profiles, servers, passwords) runs outside the workspace's composition and every gate |

`bin/konstant confinement show` prints the effective value and source of every option and, per
configured harness, how each one is enforced at level 4 and in factory mode (`enforced`,
`partial` or `no`, with the mechanism: the jail, Claude Code's settings and sandbox, the codex
profile, the gemini policy, the dsh patch); `doctor` reports the profile (WARN when it is wider
than closed), the integrity core, and the hazards below. A path option that lies inside the
integrity core is refused when the config loads.

- **`integrity = "off"`** (only with `profile = "open"`, only at level 4): no mask and no deny
  rule for the core; phases can read every token and the holdout store and write konstant's
  machinery, so `verified` no longer means anything. `doctor` reports it as a FAIL, and factory
  mode (a job with sealed holdouts, intake, the scenario writer, `holdout add`) refuses to start
  (exit 2).
- **Limits of the open profile.** The docker socket is root on this host: a level-4 phase that
  uses it can reach the core (factory mode never passes it). A phase that can ssh into THIS host
  as you (a key of yours that your own `authorized_keys` accepts; `doctor` WARNs) leaves the jail
  the same way. A phase that may write your home can plant code your own unjailed shell or agent
  sessions run later. `network = false` is enforced only where the harness separates its tool
  traffic from its model traffic (Claude Code's sandbox, codex); a jailed dsh, gemini or
  `command` phase shares the host network (`confinement show` marks it `no`).
- **What never follows the profile**: the scenario writer always runs closed (it handles sealed
  content; an open one could copy its drafts where a producer reads), and konstant's own checks
  (`task check`'s test runs, the verifier's re-run, holdout runs, probes) always run in the
  closed jail without network.
- **Host agents** (found in a live run: the orchestrator session is unjailed, and its model ran
  the host's own dsh launcher, which loads your personal dsh home): unless `host_agents = true`,
  `konstant dsh` puts refusing `dsh`, `claude`, `codex` and `gemini` launchers first on the
  session's PATH (`var/harness/dsh/session/bin/`), so running them by name exits 126 and names
  what it shadows; konstant's own commands drop that directory and still find the real CLIs. A
  program named by its absolute path is not stopped: the session is not jailed. Under the open
  profile the session's own dsh sandbox stays `workspace-write`: the profile widens phases, never
  the unjailed session.

## Security model and limits

konstant runs agents that write code, and it checks that code by running it. Read this before you
rely on any boundary.

**What konstant enforces itself, whatever the harness:** the board's roles and states (the closer
cannot verify, a reviewer cannot review its own job, a phase acts as `worker`); the evidence
contract; the DoD rules over files a phase cannot forge without being caught (verdict authorship,
the content pin, DONE.md tied to the DoD); a `verified` that needs a matched DoD probe; probe
shapes that never run a shell, never read `var/`, and never let git run a repo-configured command;
konstant's own git reads that never run a repo filter or hook; one task run per project; nothing a
phase starts outlives the phase (Linux); private file modes (`var/` 0700, the DB 0600); a board on
loopback (a remote bind needs `[board] allow_remote = true`); request bodies capped at 1 MiB.

**What is mitigated, not solved (inherent to running agent-written code):**

- **Running tests runs agent code.** `task check`, the runner's DoD loop and the verifier's re-run
  execute tests and commands an agent wrote: OUT tests, the project's test suite, a `VERIFY_CMD`.
  When bubblewrap works (`konstant doctor`: jail PASS), konstant runs them in a jail: read-only
  root, writes only to OUT, the project and a private temp dir (konstant's machinery, below,
  stays read-only even inside those), `var/secrets/` and the credential locations below masked,
  an own pid namespace, and for tests no network. Without bubblewrap (macOS, or user namespaces
  disabled) they run with your full rights. `[gate] jail = false` turns the jail off.
- **What the jail masks, exactly** (`konstant/machinery.py`; the codex profile denies the same
  set and Claude Code's sandbox read-denies it): `~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/.config/gcloud`, `~/.config/gh`, `~/.kube`, `~/.docker`, `~/.azure`, `~/.netrc`,
  `~/.git-credentials`, `~/.pypirc`, `~/.npmrc`, `~/.cargo/credentials.toml`, `~/.config/hub`,
  the agent CLIs' own homes `~/.claude`, `~/.claude.json`, `~/.codex`, `~/.gemini`, `~/.dsh`,
  `~/.config/anthropic`, `~/.config/openai`, and whatever `DSH_HOME`, `DSH_AGENTS_HOME`,
  `CODEX_HOME`, `GEMINI_CLI_HOME` or `CLAUDE_CONFIG_DIR` point at. Codex's own sandbox keeps
  `~/.codex` readable minus `~/.codex/auth.json`, and Claude Code's keeps `~/.claude` readable
  minus `~/.claude/.credentials.json` (their sandboxed shells need the rest). Everything else is
  NOT masked: other files in your home stay readable to jailed code (a key kept in
  `~/notes.txt` is readable). Keep secrets in the listed locations or out of reach.
- **The holdout store `var/holdout/` is unreadable to every phase**: the jail masks it, Claude
  Code's settings and sandbox deny reading it, the codex profile denies it and the gemini policy
  denies its file tools; a job with holdouts runs only on jailed phases. A `[holdout] store` set
  to an absolute path outside the workspace is masked and read-denied the same way, and `doctor`
  (and `holdout add`) proves the store is unreadable from inside a phase jail rather than asserting
  it. A process you run yourself, unjailed and as the same OS user, can still read it: for stronger
  separation put the store under the OS user that runs `konstant verify`.
- **A factory run composes only from a recorded catalog.** `konstant agents sync` records a
  sha256 manifest of `catalog/` (`var/machinery.json`); a factory run refuses to start, and
  `doctor` FAILs, when `catalog/` differs from it, so a level-4 phase that edited the catalog
  cannot steer a later factory run's verifying phases — the next run stops until you re-run
  `agents sync` deliberately.
- **The leak and memory scans catch common transforms.** Besides a verbatim held-out literal, the
  diff leak scan and the memory store-time scan match a literal whose case, whitespace or line
  splits changed, that was reversed, or that was base64/hex/percent-encoded (`holdout/
  transforms.py`). A custom cipher, compression, or a value split across SEPARATE notes still
  passes: read prevention (the store and the memory pools are unreadable to producers) is the
  primary control, this scan the backstop.
- **Factory mode** (a job with holdouts): every phase runs in the jail whatever the harness, with
  `var/secrets/` masked except the token of the phase's own identity and the viewer token, writes
  limited to its job clone, OUT, a private TMPDIR and a fresh per-phase harness home (claude,
  codex and gemini keep only their own credential file there, read-only), and the target project
  read-only. The network stays open (the harness needs its model), so a phase can still send what
  it CAN read somewhere; it cannot read the store, the other tokens or your credential homes.
- **The scenario writer works blind to the producers**: its jail additionally masks `var/runs/`,
  every job clone, the project's `.audits/`, the board DB, the logs and `var/factory/`, and it
  reads no token; its prompt, logs and harness home live in the sealed store (the home is deleted
  after it). A harness whose home konstant cannot relocate (`command`) never runs it.
- **konstant's machinery is read-only to every phase, whatever the harness**
  (`konstant/machinery.py`, one list read by the Claude settings, the codex profile, the gemini
  policy and the jail): `bin/`, `.venv/`, `src/`, `catalog/`, `tests/`, `install.sh`, `get.sh`,
  `pyproject.toml`, `konstant.toml`, every generated harness surface (`.claude/`, `.agents/`,
  `.dsh/`, `.gemini/`, `AGENTS.md`, `CLAUDE.md`), `var/harness/` (the relocated harness homes,
  among them the home of your own `konstant dsh` session), `var/secrets/`, the board DB and the
  bookkeeping files under `var/`, the memory vault `memory/` and its index `var/memory/`, run
  records, and any `.git/`. A writable repo's `.git/` is bound as its own read-only mount, so a
  phase cannot rename or replace it to defeat the read-only `.git/config`, `.git/hooks`,
  `.git/info` and `.git/refs/replace`; only `objects/`, `refs/`, `logs/`, the index and the loose
  top-level files a commit writes stay writable. A dsh phase gets a fresh dsh home of its own,
  removed when it ends, so nothing one phase writes there loads into a later one.
- **konstant runs its own programs from a trusted path, never a phase's.** The programs konstant
  itself runs (git, bwrap, ls, sh, its own Python) resolve from its venv and the root-owned system
  directories only (`konstant/tools.py`), never from a `PATH` entry under your home that a phase
  could write; its git runs with `GIT_NO_REPLACE_OBJECTS=1` and refuses a repository carrying a
  replace ref, a graft or a shallow file, so a `verified` commit's tree is always its real objects.
  Under the open profile's host writes, konstant's own code and interpreter are bound read-only too.
- **A closed phase's environment is an allowlist, not a denylist.** A closed phase, the web
  researcher and the scenario writer get `PATH`, `HOME`, the locale, `TMPDIR`, konstant's own
  `KONSTANT_*`, the harness's own model-key variables and the names you list in `[harness]
  env_passthrough` (or `KONSTANT_ENV_PASSTHROUGH`) — nothing else from your environment, so a host
  secret with any name never reaches a phase that does not need it. The open profile passes your
  environment by design (minus the credential denylist).
- **Unsandboxed phases are not confined.** Without bubblewrap and socat on Linux, Claude Code runs
  Bash unsandboxed (`doctor` WARNs). The allow list still decides which commands start, but an
  allowed test runner executes agent-written code with your rights: it can read your files and
  reach the network. Treat an unsandboxed workspace as "the agent has my user account".
- **Same-OS-user tokens.** Every token file is readable by the OS user that owns the workspace.
  The deny rules keep a Claude Code session away from `var/secrets/`; code run with your rights
  (above) is not kept away. Real verifier separation needs a second OS user; even then a DoD
  `VERIFY_CMD` runs agent code as that user, and only the jail masks its token.
- **A verifier phase runs the producer's code in its own window.** konstant kills what a producer
  phase leaves running before a verifier starts, and refuses a verdict changed after its phase
  ended; but a test the producer wrote, run BY the tester during the tester's own phase, could
  still rewrite the tester's verdict inside that window. The verifier's DoD probes and re-run are
  the second line.
- **Process containment is Linux-only** (a child subreaper). A process started through another
  service (cron, `systemd-run`, ssh to localhost) is out of reach; none of those is on a phase's
  allow list under the closed profile (the open one lets a phase use ssh: see "Confinement
  profiles").
- **User-level Claude Code memory.** The default command skips user-level settings, hooks and MCP
  servers. Your user-level `~/.claude/CLAUDE.md` memory is not a settings source and may still
  shape a headless phase: keep it free of instructions that would mislead a phase.
- **Folder trust.** A `claude -p` run does not apply the allow rules from the project-level
  `.claude/settings.json` of a folder you have not trusted. This is why the default command passes
  the same file with `--settings`. Interactive sessions need the trust dialog accepted once.
- **A project is the work product.** Files inside a project, its own `CLAUDE.md`, `AGENTS.md` or
  `.claude/` included, are what phases write: a producer can change what a later phase in the
  same project reads (the same window as the verifier item above). konstant protects its own
  generated surfaces at the workspace root, not a project's files; the verifier's DoD probes and
  re-run are the second line.
- **Your dsh session.** `bin/konstant dsh` is the orchestrator and is not jailed. It refuses to
  start when the generated `.dsh/` files differ from the catalog, when packages are installed in
  its dsh home, or when dsh composes anything besides its own bundles and konstant's two patches
  (or nothing readable). Phases cannot write its home (`var/harness/`).
- **Interactive mode is weaker than the runner.** Without phase manifests, verdict authorship is
  only a warning, and a session can create interactive run records with `task gate`. Use
  `task run` when the result must not depend on an agent's honesty.
- **DECLINED needs the board.** An offline check (the runner's close evidence, the verifier's
  re-run of it) never resolves a DECLINED row, so a run whose MET depends on one is closed by hand
  after the owner's note.
- **The live tree.** `verify` re-runs against the project as it is now. One run per project at a
  time is enforced; work done on the project after a job was closed can still change its re-run.
- **Redaction** removes known secret shapes, `NAME=value` assignments whose name says token,
  secret, password or key, and konstant's own tokens. A secret of no recognisable shape that an
  agent pastes into evidence is stored as written (in a 0600 DB).
- **Other harnesses** get only what their own permission system enforces, with konstant's
  generated configuration (docs/HARNESSES.md has the matrix): Codex confines writes and denies the
  privileged tokens but has no command allow list; Gemini CLI allow-lists commands but an allowed
  test runner is unsandboxed; DeepSeek Harness confines writes only, so konstant runs every dsh
  phase inside its own jail (bubblewrap): the owner, orchestrator and verifier tokens and the
  credential locations above are masked, konstant's machinery is read-only, other files stay
  readable and the network is open (without a working bubblewrap, or with `[gate] jail = false`,
  the token files are readable and role separation inside a dsh phase is procedural; `doctor`
  says which); a dsh run starts only when dsh composes konstant's own layers (fail closed); a
  `command`
  harness gets whatever the tool enforces. `konstant doctor` prints one `reach` row per configured
  harness. konstant's own jail, process cleanup, worker role and DoD rules apply to every harness.

`konstant doctor` reports the state of each of these on your machine: sandbox, jail, role
separation, file modes and the board host.

## Security reviews

Two independent security reviews ran before the first release. Each reviewer had not built the
code it reviewed, installed the release the way the README describes, attacked it with an
adversarial fake harness (a stand-in for an agent that tries to cheat) and reported each
finding with a reproduction. Every finding got a test under
`tests/review/`, written from the reproduction, that failed on the reviewed code and passes on the
fix. Test names carry the finding id (`test_F01_...`, `test_G03_...`), and DESIGN.md cites the ids
where a rule exists because of one.

| review | scope | findings (P0 / P1 / P2 / P3 / P4) | outcome |
|---|---|---|---|
| first (F-01..F-35) | the board, gate, DoD check, verifier, install and the Claude Code default | 35 (1 / 9 / 11 / 9 / 5) | 33 fixed, 2 mitigated and documented; none of P0/P1 open |
| second (G-01..G-07) | the harness adapters, the dsh plugin and jail, the one-line installer, and a regression check of the first review's fixes | 7 (1 / 2 / 1 / 1 / 2) | 7 fixed |

Classes of problem the fixes closed:

- **A cheating agent reaching `verified`**: a DONE.md row excusing a failure with invented text
  (F-01), a no-op verify command passing (F-02), a run record forged outside `var/runs/` (F-11),
  DONE.md rows not tied to the job's DoD (F-21), a FAIL row skipped by a loose header match (F-09).
- **One identity acting as two**: an author reviewing or verifying its own work (F-03), phases
  holding the orchestrator token (F-12).
- **Read-only checks that were not read-only**: git probes and konstant's own git reads running
  repo-configured filters and hooks (F-04, F-07), probes reaching `var/secrets/` (F-29), project
  paths widening the probe roots (F-13, F-35).
- **A phase changing what a later phase or the operator loads**: a background process rewriting a
  verdict (F-05), edits to `catalog/` or to another harness's generated files (F-08, G-03), a dsh
  phase writing the home of the operator's own dsh session (G-01, the second review's P0), dsh
  layers the check did not see (G-02, G-05).
- **Reach of agent-written code**: tests and re-runs now run in a bubblewrap jail (F-06, F-10),
  the credential homes of every agent CLI are masked (G-04), user-level harness settings stay out
  of a phase (F-20), the sandbox keeps the allow list authoritative (F-19).
- **Hygiene**: request size caps, broader secret redaction and private file modes (F-14, F-22,
  F-25), a pid-checked `board stop` (F-23), a loopback-only board (F-24), and in `get.sh` an
  unreadable target folder and non-file tar members are refused (G-06, G-07).

What remains is inherent to running code an agent wrote, and is listed in "Security model and
limits" above: checking tests means running them (F-06, F-10: mitigated by the jail, not solved);
a test run by the tester inside its own phase can still touch that phase's verdict (F-05
residual); the verifier re-runs against the live tree, not a pinned commit (F-28); user-level
Claude Code memory may still load (F-20); and your own dsh session is not jailed. To report a new
problem, see [SECURITY.md](../SECURITY.md).
