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
- **verified**: the run's job, once closed, has a `konstant verify` verdict.

A DONE.md row `DECLINED | <claim> | job <id>` excuses a finding only when the claim quotes it and
job `<id>` carries an owner note `DECLINED: <the same claim>` (`bin/konstant --as owner job note
<id> "DECLINED: ..."`), read from a reachable board. It never excuses the verdicts, phases,
judged, tests, verified, authorship or holdouts rules: what the verifiers, the tests and the
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
with holdouts runs only when every phase is jailed (`task run --harness dsh` today; otherwise exit
2 `holdouts need a confined phase`). The producer is told only that holdouts exist and how many.
`konstant verify` then checks the store against the hashes, scans for a leaked canary or a copied
expectation, materialises the exact commit the job closed with, and runs every scenario there
without network. A failure shows only `holdout H1 failed (hint: ...)`; PASS needs everything a
level-4 PASS needs **and** every holdout passed. Repeated failures wear a set out (it is retired
and a fresh one must be sealed); a leaked canary burns it. `holdout list` shows ids, kinds, hashes
and states, never content; `holdout show` prints one file and is refused inside a task run.

## Generated surfaces

`konstant agents sync` renders `catalog/` into `.claude/agents/<agent>.md`,
`.claude/skills/<skill>/SKILL.md` (26 skills plus one `workflow-<type>` skill per type),
`.claude/settings.json`, `CLAUDE.md` and `AGENTS.md`. Generated files carry a header and are
overwritten on every sync. Edit `catalog/` instead. `agents sync --check` (also run by `doctor`)
names every drifted file.

## Permissions model

Headless phases are **workspace-scoped** (a design decision), whatever the harness; how that maps
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
  denies its file tools; a job with holdouts runs only on jailed phases. A process you run
  yourself, unjailed and as the same OS user, can still read it: for stronger separation put
  `[holdout] store` outside the workspace, owned by the OS user that runs `konstant verify`.
- **konstant's machinery is read-only to every phase, whatever the harness**
  (`konstant/machinery.py`, one list read by the Claude settings, the codex profile, the gemini
  policy and the jail): `bin/`, `.venv/`, `src/`, `catalog/`, `tests/`, `install.sh`, `get.sh`,
  `pyproject.toml`, `konstant.toml`, every generated harness surface (`.claude/`, `.agents/`,
  `.dsh/`, `.gemini/`, `AGENTS.md`, `CLAUDE.md`), `var/harness/` (the relocated harness homes,
  among them the home of your own `konstant dsh` session), `var/secrets/`, the board DB and the
  bookkeeping files under `var/`, run records, and any `.git/` (a shell that must commit gets
  `.git/config` and `.git/hooks` read-only). A dsh phase gets a fresh dsh home of its own, removed
  when it ends, so nothing one phase writes there loads into a later one.
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
  allow list.
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
