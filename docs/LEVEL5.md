# konstant level 5: the dark factory

Status: **plan, being built**. Wave L5-1 (pillar A, sealed holdouts: section 3), wave L5-2
(factory confinement, identities, job clones: section 2), wave L5-2b (confinement profiles open /
closed and per-capability options around an integrity core: section 2.1) and wave L5-3 (pillar B,
intake from the orchestrator chat, DoD review and the scenario writer: section 4) have landed and
are described as built in DESIGN.md §7.1, §7.2, §9.1 and §7.3; "L5-1 as built", "L5-2 as built",
"L5-2b as built" and "L5-3 as built" in section 8 list where they differ from the text below. The owner answered the open questions on 2026-11-01 (section 9); the
sections they change say so. Everything else on this page is still the plan that the next
releases build in the waves of section 8; DESIGN.md, CONCEPTS.md and CLI.md change wave by wave as
each part lands, and this page stays the roadmap until level 5 is reached.

## 0. Levels

| level | who writes what | what konstant does | where the owner looks |
|---|---|---|---|
| **4** (0.1.0, shipped) | the owner writes each job and its Definition of Done (DoD) | gate -> phases -> DoD loop -> independent verify, unattended | outcomes: `verified`, or a stop with the reason written down |
| **5** (this plan) | the owner **says what he wants to his orchestrator, in chat, as today**; the orchestrator turns it into goals and limits (section 4.0) | goal -> jobs with generated DoD -> held-out acceptance scenarios -> phases -> verify -> **ship** -> post-ship checks -> rollback on failure, inside budgets | the same chat: only BLOCKED, owner decisions and budget stops are raised there; no human writes or reads code |

Level 5 is called a dark factory because nobody needs to watch it. It is only acceptable if a
model still cannot declare its own work done. Level 4 already ensures that for a job a person
wrote. Level 5 removes the person from writing jobs and from deciding to ship, so it needs two
more independent checks: tests the producer never sees (holdouts), and a ship step that undoes
itself when the shipped state fails.

## 1. What does not change

Level 5 is built on the level-4 mechanisms and keeps every rule of the two security reviews
(CONCEPTS.md, "Security reviews"). Each pillar below names the review classes it touches. The
invariants:

- **No model decides "done", "ship" or "roll back".** Classification, the DoD check, verification,
  holdout settlement, the ship guard, budget accounting and rollback are code. Models plan, write
  scenarios, write code and review; code reads the artifacts they leave. Reviewer verdicts (the
  new DoD review among them) are inputs that can stop work, as at level 4; none of them can pass
  a job or ship it. There is no LLM-as-judge at level 5 either.
- **The identity that does the work never judges it** (F-03, F-12). Level 5 adds identities
  (planner, DoD reviewer, scenario writer) and the board refuses any pair that must differ.
- **A check that cannot fail is not a check** (F-02). Every new gate ships with a planted-bad
  test, and holdout scenarios themselves must fail on the code before the work (section 3.2).
- **Machinery stays out of reach** (G-01, G-03, F-08). `src/konstant/machinery.py` stays the one
  list. Level 5 extends it and never adds a second list beside it.
- **konstant's git reads and writes never run repository-configured commands** (F-04). Ship,
  rollback and the holdout checkout use plumbing (`ls-tree`, `cat-file`, `commit-tree`,
  `update-ref`) under the same pinned git environment (`gate/rules/common.py` `GIT_ISOLATION`,
  `verify/procenv.py` `git_env`). They never use `checkout`, `merge`, `revert` or `archive`.
- **Fail closed.** An unreadable composition, a missing jail, an unmeasurable budget or an
  unreachable notifier stops the factory. It never silently degrades.
- **Replace, do not add beside.** The factory loop drives the existing runner (`gate/runner.py`
  `PhaseRunner`, `gate/loop.py` `dod_loop` / `close_and_verify`) and the existing verifier
  (`verify/verifier.py`). It does not contain a second phase engine.

## 2. Foundations shared by the four pillars

### 2.1 Factory mode means every phase is confined

A job that carries holdouts, and every phase the factory starts, runs inside konstant's
bubblewrap jail (`jail.py` `wrap`/`session`), **whatever the harness**. Before L5-2 only dsh
confined itself (`harnesses/dsh.py` `Dsh.confine`). L5-2 generalised `Adapter.confine`
(`harnesses/base.py`) so claude, codex, gemini and `command` phases run inside the same jail when
factory mode is on. Each harness keeps its own sandbox nested inside, as dsh's does.

- Without a working jail (`jail.available()` false, `[gate] jail = false`, macOS), `factory run`,
  `intake` and a `task run` of a job with sealed holdouts exit 2 with `holdouts need a confined
  phase`. Nothing falls back to "procedural".
- Inside the jail a phase can read exactly one write token, the token of its own identity
  (2.2), through `expose=`, the mechanism dsh phases already use for `worker.token`, plus the
  read-only `viewer` token (L5-2: a viewer token writes nothing, and the in-task read paths and
  the existing dsh tests use it).
- A harness needs its own credential file to reach its model. For a jailed claude or codex phase
  the jail exposes only that file, as `machinery.SELF_HOME` already does for their sandboxes.
- Verified in wave L5-2: Claude Code's own Bash sandbox DOES nest inside konstant's jail when a
  nested bubblewrap starts there, socat is installed and the phase has the jail's own short
  `/tmp` (its sandbox bridges are unix sockets under TMPDIR; a long TMPDIR fails them, even
  unjailed). Where it cannot, a claude phase in factory mode runs with Claude Code's sandbox off
  and konstant's jail as the boundary (the plan's fallback; without it every Bash call would be
  denied, because the generated settings forbid unsandboxed commands). `doctor` says which.

**Confinement profiles (owner, 2026-11-01; wave L5-2b).** Verbatim (typos kept): "so far my
experience has been that i can trst my agents not to take the shortcuts and run destructive
commands irresponsibly. my dsh has access to my servers passwords and proxmox. adding open and
closed mode is a good idea, pwrhaoes choosing what the models can see and do as options."
`konstant.toml [confinement] profile` is `closed` (the default and the public product's: the jail
shape above) or `open` (a phase gets the host like the owner's own shell: read and write anywhere
the user can, network, ssh and the ssh agent, the docker socket, the user's credential files and
variables), and per-capability options override it (`network`, `home_read`, `home_write`,
`extra_read`, `extra_write`, `credentials`, `ssh_agent`, `docker_socket`, `host_write`,
`host_agents`; CONCEPTS.md "Confinement profiles" has the table with what each allows and risks).
What no profile opens is the **integrity core**, always enforced in factory mode: the sealed
store unreadable, every token but the phase's own identity's unreadable, konstant's machinery
(`machinery.py`: catalog, generated harness surfaces, `var/` bookkeeping, the board DB with the
job's verdict history, `.git` of the workspace; in factory mode also the target and the other job
clones) not writable. It protects the meaning of "verified", not the host. Under `open` the jail
is a thin layer (the host root bound writable, masks and read-only binds over the core only) and
wraps every phase at level 4 too; the scenario writer always runs closed; factory mode never
passes the docker socket (root on the host). Outside factory mode the owner may set `integrity =
"off"` (with `open`): `doctor` FAILs and factory mode refuses to start.

### 2.2 Identities

The board already maps a token to `(label, role)` (`board/auth.py`, table `tokens`). Level 5 mints
additional tokens of role `worker` with distinct labels, one per factory identity:

| label | role | acts in | may | must differ from |
|---|---|---|---|---|
| `planner` | worker | the intake phase | file jobs under the goal's project | the DoD reviewer, the claimant |
| `dod-reviewer` | worker | the DoD review phase | post a `dod-review` trail row | the planner, the claimant |
| `scenario` | worker | the scenario-writer phase | seal holdouts for one job | the claimant, the closer |
| `worker` (unchanged) | worker | producer and verifying phases | claim, close | everyone above |
| `factory` | orchestrator | the factory process (code, never a model) | approve after a SHIP review, ship, roll back, escalate | the closer |
| `verifier` (unchanged) | verifier | `konstant verify` | post verdicts, run holdouts | the closer |

`board init` mints them (`auth.mint_missing` gains labels; `auth.rotate(conn, role, label)`
already takes a label, and `board tokens --rotate ROLE` gains `--label`). The board's guards
compare labels: `board/api/lifecycle.py` refuses `approve` when the actor label equals the job's
`requested_by`, refuses `claim` and `close` to a label that posted the job's `dod-review` or
sealed its holdouts, and the existing closer rule (`verdict`, `review`) stays. The `dod-review`
row comes from `POST /api/jobs/{id}/dod-review` (only the `dod-reviewer` label, before any claim,
never on a job it filed; L5-2). Under one OS user this separation holds because
of the jail: a confined phase cannot read another identity's token. Without the jail it would
only be procedural, which is why 2.1 makes the jail mandatory.

### 2.3 Storage map: who can read what

| path | written by | readable by producer phases | readable by the verifier |
|---|---|---|---|
| `var/holdout/<job>/` (**sealed store**, new) | `holdout add`, the scenario phase (its own `drafts/` only) | **no**: masked by the jail; read-denied by every adapter (3.3) | yes |
| `var/factory/` (goals, events, notifier spool; new) | the factory process | read-only | yes |
| `var/board.db` | the board | read-only (as today) | yes |
| `var/runs/<run>/` | the runner | read-only (as today) | yes |
| `projects/<slug>/` (the **target**: canonical repo) | ship and rollback only | read-only in factory mode | yes |
| `projects/<slug>@<job>/` (**job clone**, new) | that job's phases | read-write (`.git/config` and `.git/hooks` read-only, as today) | yes |

The board DB and run records stay readable to phases, as in 0.1.0 (the second review saw
`var/board.db` read-only in the jail and accepted it: it holds token hashes, not tokens).
**Therefore no holdout content ever enters the DB, a run record or a trail row.** The board stores
only a commitment per scenario (3.2).

`machinery.py` gains `var/holdout` (L5-1) and `var/factory` (L5-5) in `DIRS` (no phase writes them) and a new
tuple `SEALED = ("var/holdout",)` (no phase reads it). `jail.hidden()` masks `SEALED` next to
`var/secrets/`. Every adapter renders `SEALED` as a read denial (3.3). The existing test that
checks every machinery entry against every adapter
(`tests/review/test_review2_harness.py::test_G03_every_machinery_path_has_a_rule_in_every_adapter_and_the_jail`)
is extended to `SEALED`.

### 2.4 Job clones and the target

In factory mode a job's phases never touch the target repository. When a job is first claimed,
the board records `jobs.workdir` = `<project path>@<job id>` and `jobs.workdir_base` = the target's
current tip (computed by the board itself, recorded once), and the runner creates
`projects/<slug>@<job>/` from that commit. konstant writes the tree
itself from `ls-tree`/`cat-file` (the raw-blob way `gate/rules/common.py` already reads trees), so
no checkout, filter or hook runs. The clone borrows the target's object
store as a git alternate (read-only, nothing copied). The run record's `project` is the clone,
its `git_base` the clone's base (so every round's diff covers all of the job's work), and the
existing one-run-per-project lock (`cli/task_run.py` `project_lock`) applies to it. The board records the
clone on the job (`jobs.workdir`), and `verify/verifier.py` `project_dir` uses it for that job,
so the re-run and the DoD probes judge the job's own result. A DoD written for a factory job
names paths of the result as `{workdir}/...`; the verifier substitutes the clone before shape
matching (the allowlist and path roots apply to the resolved path), and the post-ship checks
substitute the target (5.3), so the same DoD probes are checked once before and once after the
ship. The target is bound read-only in every phase jail. Only the ship step (5) moves the
target's branch, and only to a commit the verifier passed. At level 5 one factory runs jobs **serially per project**, so a ship
is always a fast-forward of the commit the job was cloned from (5.2).

### 2.5 New modules and tables (sizes respect the 400-line rule)

```
src/konstant/holdout/   store.py (seal, commit, list), lint.py, leak.py, author.py (scenario phase)
src/konstant/verify/holdout.py           # materialise the pinned commit, run scenarios, settle
src/konstant/factory/   goal.py intake.py ship.py budget.py notify.py loop.py
src/konstant/cli/       goal.py factory.py holdout.py ship.py
src/konstant/board/api/factory.py        # read routes for the status view; ship/escalation writes
src/konstant/board/migrations/0002_holdouts.sql 0003_... (one per wave that adds tables)
```

The migrations (`board/migrate.py` drives them from `schema_meta.version`). L5-1 shipped
`0002_holdouts.sql`: `holdouts`, `jobs.holdout_required`, `verifications.holdout_json` and every
level-5 trail kind (one rebuild of `trail` for all of them); the other tables come with their waves:

| table | columns (essential) | rules |
|---|---|---|
| `goals` | `id, slug, project_id, spec_json, spec_sha256, status (active/paused/done/stopped), created_at` | `spec_sha256` immutable (trigger, like `jobs_acceptance_immutable`) |
| `holdouts` | `id, job_id, hid, kind (proof/regression), sha256, author_label, sealed_at, trail_id, generation, state (sealed/burned/retired)` | no delete; `sha256` immutable; no content column; `trail_id` orders the seal against claims, `generation` numbers the sets |
| `ships` | `id, job_id, goal_id, target, commit_sha, pre_ref, rollback_sha, state (shipped/rolled_back/rollback_failed), post_json, created_at, updated_at` | append-only state changes |
| `budget_ledger` | `id, goal_id, job_id, run_id, kind (wall_s/task_runs/phases/tokens/cost/rollbacks), amount, at` | append-only (trigger, like `trail_no_update`) |
| `escalations` | `id, goal_id, job_id, kind, reason, delivered_at, acked_by, created_at` | append-only except `delivered_at`/`acked_by` |

`jobs` gains `goal_id`, `holdout_required`, `workdir` (the job clone) and `budget_json`
(`workdir` with `workdir_base`, the target commit the clone starts from, shipped in L5-2's
`0003_workdir.sql`).
`verifications` gains `holdout_json` (scenario ids, pass/fail, the commit and the commitment
digest, never a command or an output).
`trail` kinds gain `dod-review holdout ship rollback escalation budget`.

## 3. Pillar A: holdout acceptance scenarios (first; B, C and D depend on it)

### 3.1 What a holdout is

A holdout is a black-box acceptance scenario for one job. It is written **before** the producer
claims the job, stored where no producing phase can read it, and run **only by the verifier**,
against the exact commit the job closed with. The producer is told only that holdouts exist and
how many. No phase ever runs a holdout: konstant's verifier code runs them, once against the
base before any producer exists (the negative control, 3.2) and at verification against the
closed commit (3.6). A job with holdouts reaches `verified` only when every holdout passed, in
addition to everything level 4 already requires.

File format (one scenario per file, `var/holdout/<job>/H<n>.scenario`):

```
SCENARIO: greet uses the caller's name
KIND: proof
RUN: python3 -c "from greeter import greet; print(greet('Ada'))"
EXPECT_EXIT: 0
EXPECT_OUT: hello Ada
HINT: names other than the default are used verbatim
CANARY: khc-6c1d0f0e9b2a47d8a3f5
```

- `KIND: proof` must FAIL before the work; `regression` must PASS before and after. A line that
  starts with `#` is a comment; a value runs to the end of its line, so an expectation may hold `#`.

- `RUN` is a command, as a DoD `VERIFY_CMD:` is, but it is split with shlex and runs as an argv,
  never through a shell: a control character, or a shell operator (`; & | < >`, a backtick, `$`)
  outside quotes is refused. It may not call a test runner (`pytest`,
  `unittest`, `npm test`, ...). A project's conftest, plugins or test config could rewrite a test
  runner's verdict, so a holdout drives the product's own interface.
- The expectation never enters the jail. The verifier matches stdout and the exit code outside
  the process. `EXPECT_OUT` compares the whole stripped output. `EXPECT_RE` must fullmatch the
  whole output, so a product that sprays every possible answer onto stdout still fails. It also
  must not be trivial (`verify/probe.py` `trivial_expect`, the rule PROBE lines already follow).
- `CANARY` is a random 20-hex string. It is the salt of the commitment (3.2) and the marker for
  leak detection (3.5).
- `HINT` is the only text a failing holdout ever reveals (3.6). Lint refuses a hint that contains
  a token of `RUN` or of the expectation.

### 3.2 Sealing and commitment

`konstant holdout add JOB --file F` (owner or the `scenario` identity) and the scenario phase
(3.4) both end in `holdout/store.py` `seal()`:

1. **Lint** (`holdout/lint.py`, deterministic):
   - every key is present, and `RUN` parses as an argv under the rules of 3.1 (the probes'
     stricter character rules would refuse the `;` inside a quoted `python3 -c` argument);
   - the expectation is not trivial;
   - **held out**: no expectation literal of 4 or more characters and no quoted `RUN` argument
     appears in the job's brief or acceptance (`NOT HELD OUT: H1 ...`);
   - the job, counting its sealed scenarios and the files of this `holdout add` (`--file` is
     repeatable), has at least `[holdout] min_per_job` scenarios (default 2), at least one of
     them `proof`, and no canary twice.
2. **Negative control.** Every scenario is run once against the job's base commit (the target
   tip the clone starts from), the same way the verifier will run it (3.6). A `proof` scenario
   that already passes on the base checks nothing: `VACUOUS: H1 passes before the work`. A
   `regression` scenario that fails on the base is refused as well. This is the evidence
   contract's `CONTROL_CMD` (`board/evidence.py`) applied to holdouts.
3. **Commit.** The board stores `sha256(file bytes)` per scenario in `holdouts`, with
   `author_label` and `sealed_at`. The store file becomes `0400` in a `0700` directory.
4. **Claim guard.** For a job with `holdout_required` (every factory job), `claim` answers 409
   `no holdout sealed` while the job has fewer than `min_per_job` sealed scenarios. The verifier
   also checks that `sealed_at` of every scenario it runs is earlier than the claim that started
   the round it judges. A rotated set (3.6 step 6) is sealed while the job is back in `queued`,
   so it too exists before the producer's next claim, and its writer still sees only the target,
   never the job clone.

Owner-written scenarios: `holdout add` **moves** the source file into the store and refuses a
source anywhere inside the workspace (phases can read the workspace), so no copy stays where a
phase can read it. The CLI refuses
`holdout show` under `KONSTANT_IN_TASK=1`, and `holdout show` reads the store directly. No board
route serves scenario content.

### 3.3 Proof that producing phases cannot read the store

| reader | mechanism (existing code it extends) | level |
|---|---|---|
| any jailed process: dsh phases, every factory phase (2.1), agent tests in `task check` (`gate/rules/tests.py` `run_cmd`), verifier re-runs (`verify/rerun.py` `_run_group`) | `jail.hidden()` gains `machinery.SEALED`: an empty tmpfs over `var/holdout/` | enforced |
| Claude Code tools | `agents/settings.py` `render`: `Read(<ws>/var/holdout/**)` in `deny` (next to the existing `var/secrets` rule), plus the sandbox `denyRead` | enforced for tools; Bash covered by the jail |
| codex | `harnesses/codex.py` `filesystem()`: `var/holdout/**` = `deny` (as the privileged tokens are) | enforced |
| gemini | `harnesses/gemini.py` `policy()`: deny `read_file`, `read_many_files`, `glob`, `search_file_content` under `var/holdout/` | tools enforced; shell covered by the jail |
| `command` harness | none of its own | the jail only |
| a probe (`PROBE:` line) | `verify/shapes.py` `Roots.locate` already refuses every path under `var/` (F-29) | enforced |
| the board API, run records, trail | content never stored there (2.3) | n/a |
| an unjailed process run by the owner's own user (an interactive session, an unsandboxed tool) | not confined (CONCEPTS "Security model and limits"); for stronger separation see 3.8 | none |

The rule that makes this a proof and not a hope: **a job with sealed holdouts never runs on an
unconfined phase** (2.1). A test plants a reader in every harness path (the fake harness for
`command`, the stub dsh for dsh, the rendered settings, profile and policy for claude, codex and
gemini) and asserts each one is denied. It goes red when `SEALED` loses its entry.

### 3.4 Who writes scenarios

- **The owner** may add scenarios to any job while it is not claimed (`holdout add`).
- **The scenario writer**: a new role agent `scenario-writer` (`catalog/agents/scenario-writer.md`;
  `catalog.py` `ROLE_AGENTS` grows from `("orchestrator",)` to include it, so the one-agent-per-type
  invariant stays). `holdout/author.py` runs it as one phase through the existing
  `gate/harness.py` `HarnessSet.run`, with the profile composed once by `Generator.agent_prompt`
  (the F-08 snapshot rule), as identity `scenario`:
  - **input**: the goal text, the job's brief and DoD, and a **read-only view of the target**.
    It never sees a job clone, the producer's OUT, its phase logs or any verdict; the claim guard
    (3.2) makes sure no producer output exists yet.
  - **writes**: only `var/holdout/<job>/drafts/`, which the jail binds writable for this phase
    alone. Its run dir (prompt file, `phases/*.log` and harness transcript) lives under
    `var/holdout/<job>/runs/`, never under `var/runs/`, because a transcript of a scenario writer
    contains the scenarios.
  - **its harness home**: relocated into the sealed store and deleted after the phase. dsh already
    gets a fresh home per phase. An adapter that cannot relocate where it keeps session
    transcripts is refused for the scenario role (`Adapter.relocatable_home`, new; `doctor` names
    it). Otherwise a later producer on the same harness could read the scenario writer's
    transcript from the shared harness home.
  - then `seal()` (3.2) runs lint and the negative control on every draft. A refused draft goes
    back to the writer once with the lint reasons. Another refusal escalates the job as
    `holdout-authoring BLOCKED`.
- **Independence comes from identity, context and file isolation, not from a second model**
  (owner decision Q1, section 9: one local model plays every role, the scenario writer
  included). The scenario writer is a different identity (the board refuses it the claim and the
  close), sees a different context (the goal, the brief and DoD, a read-only target; never a job
  clone, a producer's output or a verdict), and writes where no producer can read (the jail).
  Its scenarios must still FAIL on the base (the negative control) and stay out of the brief (the
  held-out lint), which a scenario that merely restates the producer's own reading of the brief
  cannot pass. `[holdout] writer_harness` / `writer_model` stay available to name another harness
  or model; `doctor` reports a single-model setup as INFO ("supported; separation by identity,
  context and isolation"), never as a WARN or a refusal. Nothing in the design requires a second
  model.

### 3.5 Leak detection

Reads are prevented (3.3). Detection covers what prevention cannot reach: a scenario pasted
somewhere by a person, a harness that keeps transcripts in a place nobody knew about, a hole not
yet found. `holdout/leak.py` runs in the verifier before any scenario:

1. **Canaries**: each scenario's `CANARY` is searched, as raw bytes, in the job clone's diff
   against base (listed with plumbing, as `gate/rules/judged.py` does), in OUT, in every phase
   log and prompt of the job's runs, and in the job's trail. A hit means `LEAK: canary of H2 found
   in <path>`.
2. **Literals**: distinctive literals of `RUN` and of the expectation (4 or more characters, not
   present in the brief) that appear in **added** lines of the diff mean `LEAK-SUSPECT: ...`. A
   hard-coded expected answer is exactly what teaching to the test produces.
3. **Commitment**: the store file hashes must equal the board's `holdouts.sha256`, otherwise the
   result is `holdout commitment mismatch` (BLOCKED: the store was changed after sealing).

A LEAK burns the job's holdout set (`state = burned`) and makes the verdict BLOCKED (the job stays
`completed_unverified`, as every BLOCKED verdict leaves it, so it can never ship). The factory
escalates `LEAK` as an owner decision: find the path, then reopen the job with a fresh set, or
cancel it. A LEAK-SUSPECT fails the
verification round like a failed holdout and is escalated if it repeats.

### 3.6 Running holdouts (verifier only)

`verify/holdout.py`, called from `verify/verifier.py` `verify_job` after the probes and the
re-run:

1. The commit is the evidence's `COMMIT=` (the runner adds it when it closes a factory job). The
   tree is **materialised by konstant** from `ls-tree`/`cat-file` into a private temp dir (no
   checkout, no filters, no hooks: F-04). This pins the run to the closed commit and closes the
   live-tree limit F-28 for holdouts.
2. Each `RUN` executes in `jail.session` with `net=False` (as the tests rule already runs agent
   tests). The only writable bind is the temp dir, the sealed store is masked, the env is scrubbed
   (`verify/procenv.py` `scrub_env`), and the timeout is `[holdout] run_timeout_s`. The temp dir is
   bound at the job clone's own path, so the code under test sees the same path, env and jail
   shape as the tests rule. A product that tries to behave differently "under holdout" has nothing
   to tell the two apart by.
3. The temp dir is deleted afterwards. Nothing a scenario run writes persists, so a product that
   logs its inputs to a file leaves nothing for the next round.
4. **Settle** (`settle()` gains a holdout argument): PASS needs everything level 4 needs (at
   least one DoD probe matched, no contradiction, re-run ok) **and** every holdout passed **and**
   no LEAK. A failed holdout or a LEAK-SUSPECT is FAIL. A commitment mismatch or an unrunnable
   holdout is BLOCKED. Holdouts add a condition and never replace one: holdouts alone can never
   pass a job (F-02).
5. **Redacted findings.** The verdict's reasons and the trail say only `holdout H2 failed (hint:
   names other than the default are used verbatim)`. No command, expectation, input or output
   leaves the verifier. `verifications.holdout_json` stores ids, pass/fail and timings.
6. **Exposure budget.** Each failed round reveals at most the hints. After `[holdout]
   max_failed_rounds` (default 2) the set counts as worn: the job goes back to `queued`, and the
   factory has the scenario writer author a fresh set for it (the old set is `retired`). After a
   second worn set the job is BLOCKED and the owner decides.
7. `rules/done.py`: DECLINED can never excuse a holdout (holdouts join verdicts, phases, judged,
   tests, verified and authorship as unexcusable rules: F-01). A producer that believes a holdout
   contradicts the DoD writes `DISPUTE | H2 | <why>` in DONE.md. A dispute is never resolved
   automatically: it is escalated as an owner decision.

### 3.7 Threat model: how a cheating producer attacks, and what stops it

| attack | what stops it |
|---|---|
| read the store (`cat`, an editor tool, `find /`) | jail tmpfs + adapter read denials (3.3); a phase cannot run outside the jail in factory mode (2.1) |
| read the board DB or run records for the scenarios | content never stored there; the DB holds salted hashes only (the canary is the salt, so brute-forcing the preimage is not feasible) |
| read the scenario writer's transcript in the shared harness home | scenario phase homes are relocated into the store and deleted; non-relocatable adapters refused for that role (3.4) |
| hard-code the visible DoD example (`greet('world') == 'hello world'` only) | proof scenarios use inputs that are not in the DoD (the held-out lint, 3.2); the literal scan catches copied expectations (3.5) |
| learn the scenarios from failure messages over rounds | redacted findings, hints linted against inputs, exposure budget, rotation (3.6) |
| a product that records its inputs during the holdout run | throwaway materialised tree, no network, nothing persists (3.6) |
| detect "I am under holdout" and behave differently | same path, env and jail shape as the tests rule; the expected answer is never inside the process; post-ship probes run in the real target (pillar C) |
| print every candidate answer | `EXPECT_OUT` is equality, `EXPECT_RE` is fullmatch over the whole output |
| plant a conftest, `sitecustomize.py` or `.pth` that fakes results | holdouts may not call a test runner; a hook cannot know an expectation that is not in the jail; ship escalates diffs that add import hooks or project instruction files (5.4) |
| change the DoD to weaken it | `jobs.acceptance` is immutable (DB trigger), as in 0.1.0 |
| change a sealed scenario | store not writable by any phase (machinery `DIRS`); commitment check |
| write its own "holdout" after the fact | claim guard + `sealed_at` before the claim of the round being judged; `scenario` label must differ from the claimant |
| excuse a failing holdout in DONE.md | DECLINED cannot excuse holdouts; DISPUTE only escalates (3.6) |
| rewrite the verifier's verdict from a background process | holdouts run in the verifier process after every phase ended and was reaped (F-05: `gate/reaper.py`) |

### 3.8 Limits of pillar A (stated, not hidden)

- Holdouts raise the cost of cheating. They do not prove correctness: a scenario writer can miss a
  case, or write a wrong expectation (the DISPUTE path handles the second).
- Under one OS user, a process the owner runs unjailed can read the store. Strongest mode: the
  store is owned by a second OS user who runs the verifier (`[holdout] store` outside the
  workspace, readable only by that user), the existing "OS-separation mode" of `verify`
  (`verifier.separation`). `doctor` reports which mode applies (owner decision Q3: not required).
- Network stays open in producer phases (the harness needs it to reach its model). Holdouts do not
  depend on that: the store is unreadable whatever the network.

### 3.9 Acceptance (pillar A)

`$WS` is a workspace installed from the release tarball, board started, factory mode on, the fake
harness configured (`tests/fixtures/fake_harness.py`, extended with the modes named below), and
job 2 a `code` job in project `greeter` with two sealed scenarios.

| # | command | expected |
|---|---|---|
| A1 | `python -m pytest -q tests/holdout` | exit 0; each lint rule, the negative control, the leak scan and settle have a `_red` and a `_green` test |
| A2 | `bin/konstant holdout list 2 --json` | `"count": 2`, one `"sha256"` per scenario, `"state": "sealed"`; the output holds no `RUN`, `EXPECT` or `CANARY` text (`grep -c khc-` = 0) |
| A3 | `python -m pytest -q tests/holdout/test_sealed_reach.py` | exit 0: the jail, the Claude settings, the codex profile and the gemini policy each deny `var/holdout`; red when `machinery.SEALED` is emptied |
| A4 | `FAKE_HARNESS_MODE=peek bin/konstant task run --job 2 --project greeter "[type:code] add greet()"` then `grep -h "peek:" $WS/var/runs/*/phases/*.log` | `peek: var/holdout empty or masked`, `peek: holdout show refused`; no line `peek: READ` |
| A5 | `FAKE_HARNESS_MODE=overfit ... task run --job 2 ...; RC=$?`, then `bin/konstant task check <run> --offline` and `bin/konstant job show 2 --json --trail` | `RC=3` (verify FAIL after close); the offline check exits 0 (the visible DoD is met); the job's last verification is FAIL with `holdout H1 failed (hint: ...)`; `grep -c "Ada"` over that JSON = 0 |
| A6 | a `proof` scenario that passes on the base: `bin/konstant holdout add 2 --file h3.scenario` | exit 1 `VACUOUS: H3 passes before the work` |
| A7 | a scenario whose expectation is in the job's DoD | exit 1 `NOT HELD OUT: H3 expectation appears in the DoD` |
| A8 | `FAKE_HARNESS_MODE=leak` (the test hands the fake producer one canary through its environment, standing in for a leak path nobody found; it writes it into its code) then `verify 2 --json` | `"verdict": "BLOCKED"`, `LEAK: canary of H1 found in greeter.py`; `holdout list 2 --json` shows `"state": "burned"` |
| A9 | the owner edits a sealed file, then `verify 2 --json` | `"verdict": "BLOCKED"`, `holdout commitment mismatch: H1` |
| A10 | `bin/konstant verify 2 --json` after an honest run | `"verdict": "PASS"`; every holdout row carries `"commit"` equal to the evidence `COMMIT=` and `"net": false` |
| A11 | `bin/konstant job claim 2` on a factory job with no sealed scenario | exit 1, HTTP 409 `no holdout sealed` |
| A12 | `KONSTANT_NO_JAIL=1 bin/konstant task run --job 2 ...; RC=$?` | `RC=2`, `holdouts need a confined phase` |
| A13 | a DONE.md row `DECLINED \| holdout H1 ... \| job 2` with an owner note | the holdout failure stays (`DECLINED` never excuses holdouts) |

## 4. Pillar B: autonomous intake

### 4.0 Intake is the orchestrator chat (owner decision, section 9)

The owner keeps talking to his orchestrator exactly as today: a gated dsh session
(`bin/konstant dsh`, the web/chat route of his dsh installation; docs/DSH.md). **That
conversation is the intake.** When the owner asks for work, the orchestrator does not do it in
the chat and does not write code: it turns the request into a goal (section 4.1) and hands it to
the factory, then reports back in the same chat.

1. **Goal from chat.** The orchestrator writes the goal file from what the owner said - the goal
   text, the project, and the limits the owner named, else the workspace defaults
   (`[factory] defaults`: `max_attempts = 3`, nothing else required; Q5) - and runs `bin/konstant
   goal add FILE --from-chat`. In this configuration `goal add` accepts the `orchestrator` role
   for a chat goal (`[factory] goal_roles`, default `["owner", "orchestrator"]` for this
   workspace's config, `["owner"]` in the public default). The goal records `source = "chat"` and
   the requesting session; its spec is copied and hashed as in 4.1, so nothing the orchestrator
   or a phase writes later changes it.
2. **Confirmation stays a chat sentence, not a gate the owner must learn.** Before `goal add` the
   orchestrator states in one line what it will file (project, goal text, limits) and files it
   on the owner's yes; a goal never starts from a message the owner did not send (a phase's
   output, a web page, a file in a repo: prompt injection through content is not intake).
3. **Report back in the chat.** The factory's escalations (`BLOCKED`, `DECISION`, `BUDGET_STOP`,
   `LEAK`, `ROLLBACK_FAILED`, `HALTED`) go to `[notify] kind = "chat"`: the gated session shows
   new events at the start of the owner's next turn (the konstant-gate plugin reads
   `var/factory/events.jsonl` and `factory status`), and outcomes (`SHIPPED`, `GOAL_DONE`) when
   the owner asks. Answering an escalation is again a chat sentence the orchestrator turns into
   the owner verb (`ship --approve-decision`, `goal resume`, `factory ack`), which still needs
   the owner role (the orchestrator session asks the owner to confirm, as for any owner verb).
4. **The orchestrator is not a factory phase.** It is the owner's own session, unjailed, acting
   as `orchestrator`; it never claims, closes, verifies or ships a factory job (it holds none of
   the identity tokens of 2.2), so a goal it files goes through the whole loop below like any
   other.

Goal files stay the mechanism underneath (and `goal add FILE` as owner stays a path for anyone
who prefers files).

### 4.1 Goal file

The goal and its limits, nothing else (written by the orchestrator from the chat, 4.0, or by the
owner):

```toml
# goals/greeter.toml
[goal]
id = "greeter"
project = "greeter"                 # an existing konstant project (its path rules: F-13)
text = """
A small greeting library: greet(name) and a CLI `greet NAME`, documented in README.
"""

[limits]                            # owner decision Q5: only max_attempts is required
max_attempts = 3                    # attempts (task runs) per job before it is BLOCKED; default 3
# optional, 0 or absent = not limited:
wall_clock = "0"                    # e.g. "4h"
max_task_runs = 0                   # for the whole goal
max_jobs = 8
max_rollbacks = 2
max_tokens = 0                      # > 0 needs a harness that reports usage (6.2)
max_cost_usd = 0

[ship]
target = "github"                   # github | branch | apply | command (5.1); github is this
                                    # owner's default (Q2), the public default stays branch
branch = "main"
post_probes = ["PROBE: test -f projects/greeter/README.md => ^ok$"]

[holdout]
author = "agent"                    # agent | owner (owner: jobs wait for `holdout add`)
min_per_job = 2
```

`konstant goal add FILE` (owner role; `--from-chat` also orchestrator, 4.0) validates the file (`factory/goal.py`), copies it into
`var/factory/goals/<id>.toml` (machinery: no phase writes it) and records `spec_sha256` in
`goals`. The factory reads only that copy, so editing the source file later changes nothing.
`goal list|show|pause|resume|cancel` complete the verbs.

### 4.2 From goal to jobs

1. **Planner phase.** `konstant intake GOAL` starts a task run of a new task type `intake`
   (`catalog/types.yaml`: agent `planner`, phases planner (producer) -> reviewer
   `DOD-verdict.md`). The type is reachable only with `--type intake`: its keyword regex matches
   nothing, and a catalog test asserts the classifier never returns it. The planner runs as
   identity `planner` and writes `OUT/BACKLOG.md` (rows `B<n> | <type> | <title> | after:B<m>`)
   and one brief per row, `OUT/jobs/B<n>.md`, each with a `DoD:` section, `PROBE:` rows (paths
   of the result as `{workdir}/...`, 2.4) and optionally a `VERIFY_CMD:`.
2. **DoD review phase.** The `reviewer` agent, as identity `dod-reviewer`, reads the goal and the
   briefs and writes `DOD-verdict.md`, `# VERDICT: SHIP|FIX`, with one line per job. Its
   authorship is checked by the existing `rules/authorship.py`, and `# JUDGED:` pins `BACKLOG.md`
   and every brief (`rules/judged.py`), so a brief changed after review is UNMET. FIX goes back to
   the planner through the existing back-edge (3 cycles).
3. **Deterministic filing** (`factory/intake.py`, after `task check` is MET):
   - every brief must pass `board/dod.py` `lint` with **no** warnings: each DoD row that
     describes live state carries a PROBE, and no PROBE is refused;
   - every job has at least one PROBE (otherwise it could only end BLOCKED: F-02);
   - every type is a known type, and `infra`/`security` jobs are marked `ship = decision`
     (owner decision Q4: only `infra`; `security` jobs ship unattended like code);
   - the backlog fits `max_jobs`, and every `after:` points at an earlier row (no cycles);
   - then each job is filed under the goal's project root with `approval_required`, `goal_id`
     and `budget_json` (its share of the goal's limits), as identity `planner`. A brief that fails
     a rule files nothing: intake exits 3 with one reason per line.
4. **Approval.** For each job, the factory process posts the review row the verdict file states
   (`dod-review SHIP`, actor `dod-reviewer`) and then `approve` as `factory`. The board refuses
   `approve` in a factory project unless a `dod-review SHIP` row exists whose actor differs from
   `requested_by` (2.2).
5. **Holdouts.** For each approved job the scenario writer runs (3.4), or the job waits for the
   owner's `holdout add` when `author = "owner"`. The claim guard holds the job until it is sealed.

The order is the point: **DoD, review and holdouts all exist before any producer runs**, and each
comes from a different identity.

### 4.3 Threat model (pillar B)

| attack | what stops it |
|---|---|
| a planner writes a trivially satisfiable DoD | lint without warnings, at least one PROBE per job, DoD review by another identity, and holdouts by a third identity that must fail on the base (3.2) |
| a planner and producer collude (same model, the owner's default: Q1) | distinct labels enforced by the board; distinct contexts (the producer never sees the DoD review or the scenarios, the scenario writer never sees the producer's work); holdouts must fail on the base and stay out of the brief; another harness/model optional |
| an injected text in a phase output, repo file or web page poses as the owner in the chat intake | a goal starts only from a message the owner sent in the session, confirmed in one line (4.0 step 2); the orchestrator holds no identity token; every filed job still passes lint, DoD review, holdouts and the verifier |
| a brief changed after the review | `JUDGED` pin over the backlog and briefs; the board stores the acceptance immutably at filing |
| a producer of job 1 plants instructions in the repo for later planners or scenario writers (prompt injection through shipped content) | ship escalates any diff to project instruction surfaces (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `.agents/`, `.dsh/`, `.gemini/` inside the project) as an owner decision (5.4); scenario lint and the negative control bound how weak a scenario can be |
| intake files jobs in another project or outside the goal | filing only under the goal's project root; projects keep their F-13 path rules |
| intake floods the board | `max_jobs`, `max_task_runs`; intake runs once per goal unless the owner re-opens it |

### 4.4 Acceptance (pillar B)

| # | command | expected |
|---|---|---|
| B1 | `bin/konstant --as owner goal add examples/greeter/goal.toml` | `goal greeter added (sha256 ...)`; a copy at `var/factory/goals/greeter.toml` |
| B2 | the same file with `[limits] max_attempts = 0` (the only required limit, Q5) | exit 1 `goal: limits.max_attempts must be >= 1`; a file without `wall_clock`, `max_task_runs`, `max_tokens` or `max_cost_usd` is accepted |
| B3 | `bin/konstant intake greeter; RC=$?` (fake harness) | `RC=0`; `bin/konstant job list --project greeter --json` lists the backlog jobs in `waiting_approval` and then `queued`; `bin/konstant job lint <each brief>` exits 0 |
| B4 | `FAKE_HARNESS_MODE=weak-dod bin/konstant intake greeter; RC=$?` | `RC=3`, `UNMET: job B2 DoD has no PROBE`; no job filed |
| B5 | `bin/konstant job show <job> --json --trail` | trail actors in order: `planner` (add), `dod-reviewer` (dod-review SHIP), `factory` (approve), `scenario` (holdout x2); pairwise distinct |
| B6 | a test posting `approve` with the requester's own label | HTTP 403 `the requester cannot approve its own DoD` |
| B7 | a test where `dod-reviewer` tries `claim` | HTTP 403 `the DoD reviewer of a job cannot claim it` |
| B8 | `bin/konstant task classify "intake the backlog for the goal"` | the type is not `intake` |
| B9 | `python -m pytest -q tests/factory/test_scenario_isolation.py` | exit 0: the scenario phase's prompt names no job clone, OUT or run path; its run dir lies under `var/holdout/` |
| B10 | `bin/konstant job show <job> --json` | `"goal_id"` set, `"budget"` with the job's share of the limits |
| B11 | chat intake: the fake orchestrator session receives an owner message, confirms it, runs `goal add --from-chat` as `orchestrator`; then an injected "owner message" inside a phase log | the goal exists with `"source": "chat"`; the injected text files nothing; an escalation of that goal appears in the session's next turn (`[notify] kind = "chat"`) |

## 5. Pillar C: auto-ship

### 5.1 Targets

| target | ship | post-ship | rollback |
|---|---|---|---|
| `github` (this owner's default, Q2; opt-in by config in the public product) | push `<commit>` to a branch `konstant/ship-<n>` of the target's GitHub remote, open a pull request into `[ship] branch` with `gh pr create`, then merge it with `gh pr merge --merge --match-head-commit <commit>` (the merge refuses a head that moved); the shipped state is the remote branch's new tip, fetched back | `post_probes`, the project's own tests and the regression set (below) on the fetched new tip | a revert: `commit-tree <pre>^{tree} -p <tip>` ("roll back ship N"), pushed as `konstant/rollback-<n>` and merged through its own pull request (`gh pr merge`); never a force-push, never a branch delete; then the fetched tip's tree must equal `<pre>^{tree}` |
| `branch` (the public default) | `update-ref refs/heads/<branch> <commit> <pre>` in the target repo (compare-and-swap; fast-forward only) | `post_probes`, the project's own tests and **every holdout of every job shipped so far** on the new tip | `commit-tree <pre>^{tree} -p <tip>` -> a new "roll back ship N" commit, then `update-ref` (CAS) |
| `apply` | materialise `<commit>` into `[ship] apply_dir`, keeping the previous tree as `apply_dir.prev` | `post_probes` against `apply_dir` | swap `apply_dir.prev` back |
| `command` | the owner's `ship_cmd` template (e.g. a `gh pr create` or a deploy script), run by the factory process with `{commit}`, `{branch}`, `{job}` | `post_probes` | the owner's `rollback_cmd`; a target without one may not auto-ship |

The branch and github targets never rewrite history. A rollback adds a commit whose tree equals
the pre-ship tree, so the shipped commit stays an ancestor and the record stays readable. A target
branch that is checked out in a non-bare worktree is refused (`update-ref` would leave that
worktree stale); `apply` is the target for a working directory.

The `github` target (owner decision Q2) is the only built-in target that uses the network. It runs
in the factory process, outside every phase, with the owner's own git and `gh` credentials, which
no phase can read (`~/.config/gh`, `~/.git-credentials` and the rest of `machinery.CREDENTIALS`
stay masked in every phase jail). Before any push the factory runs the release scanner's patterns
(`release/patterns.toml` plus the maintainer denylist when present) over the diff `pre..commit`
and refuses the ship with a `DECISION` on a finding: a dark factory must not publish a token or an
address a producer pasted. The push and the merge use the pinned git environment for konstant's
own git calls; `gh` is called with an explicit `--repo` from `[ship] github_repo`, never inferred
from a repo's config. Branch protection on the remote is respected, not bypassed: a merge the
remote refuses is a ship failure (`target refused: ...`), an owner decision.

### 5.2 The ship guard (board-side and code-side)

`konstant ship JOB` (`factory/ship.py`, identity `factory`) ships only when **all** hold. The
board checks the same conditions again on `POST /api/jobs/{ref}/ships`:

1. the job is `verified`, and its latest `verifications` row is PASS;
2. that row's `holdout_json` lists at least `min_per_job` holdouts, all passed, with the
   commitment digest equal to `holdouts.sha256` for each, and states **no LEAK**: **never ship
   without a matched holdout**;
3. the commit those holdouts ran on equals the evidence `COMMIT=` and the commit about to be
   shipped;
4. the target tip (for `github`: the remote branch's tip, fetched) still equals the job clone's
   base (`pre`, `jobs.workdir_base` since L5-2). With jobs serial per project only
   something outside the factory can move it, so a mismatch is `target moved`, an owner decision
   (5.4), never a silent rebase;
5. the job's type and diff are not an owner decision (5.4);
6. the goal is active, its budget has room, and shipping is not halted (6.3);
7. one ship at a time per workspace (a lock beside `project_lock`).

`ship --dry-run --json` prints the decision and every reason. A level-4 job (no holdouts) is
never shipped by the factory: the guard's rule 2 fails.

### 5.3 Post-ship and rollback

After the ref moves, the factory runs the post-ship checks: the goal's `post_probes` and the
job's own DoD probes with `{workdir}` set to the target (allowlisted `PROBE:` shapes,
`verify/probe.py` `run_line`), the project's own test command in the jail, and
the **regression set**: every holdout of every job this goal has shipped, run on the new tip the
way 3.6 runs them. Any failure, or a check that cannot run, triggers an automatic rollback:

1. the rollback commit or swap (5.1), as `factory`;
2. a check that the target's tree equals the pre-ship tree (`rev-parse <tip>^{tree}` against
   `<pre>^{tree}`, plumbing);
3. `ships.state = rolled_back` and a `rollback` trail row naming the failed check (redacted the
   same way as holdout findings);
4. the job stays `verified`: that state is terminal (the `jobs_terminal_is_final` trigger) and a
   verification of the clone was true. The factory files a **follow-up job** under the same
   parent, as identity `factory`: the original acceptance plus the failed post-ship check as a new
   `PROBE:` row, written by code, never by a model. The original holdouts are sealed again for
   it (same files, same commitments), and it goes through the whole loop. After `max_rollbacks`
   for the goal, the next rollback escalates `BLOCKED` instead of filing a follow-up.

If the rollback itself fails (CAS lost, `rollback_cmd` non-zero, tree mismatch), the result is
`state = rollback_failed`. **All shipping for the workspace halts**: no further ship until the
owner runs `bin/konstant --as owner factory resume-shipping`. The escalation `ROLLBACK_FAILED`
goes out. Nothing is retried, forced or reset.

### 5.4 Owner decisions at ship time

The factory ships nothing that needs judgement beyond the checks. These stop as an owner decision
(escalation `DECISION`, job kept `verified`, not shipped):

- a job type in `[ship] decision_types` (owner decision Q4: default `["infra"]`; `security`
  jobs ship without the owner, see the threat row in 5.5);
- a diff that adds or changes project instruction surfaces (`AGENTS.md`, `CLAUDE.md`, `.claude/`,
  `.agents/`, `.dsh/`, `.gemini/`, `.github/workflows/`), import hooks (`sitecustomize.py`,
  `usercustomize.py`, `*.pth`) or `conftest.py` outside test dirs;
- a job with only `regression` holdouts (nothing proved the change) unless the goal allows it;
- a target that moved outside the factory (5.2 rule 4);
- a DISPUTE row (3.6).

`bin/konstant --as owner ship JOB --approve-decision` ships it after the owner decides. The owner
does not have to read the code to decide: the escalation names the rule that stopped the ship.

### 5.5 Threat model (pillar C)

| attack | what stops it |
|---|---|
| the producer moves the target branch itself (`git update-ref` in the target) | the target is read-only in every factory phase jail (2.4); the producer only has its job clone |
| the producer pushes somewhere | no credentials in a phase (`machinery.CREDENTIALS` masked); the built-in targets never push |
| ship a commit other than the one verified | guard rules 2-3 on both sides; CAS on the ref |
| a repo-configured filter or hook runs during ship or rollback | plumbing only, pinned git env (F-04); no checkout, merge or revert |
| code that passes on the clone and breaks on the target | post-ship checks on the real target, regression set, automatic rollback |
| two ships racing | one ship at a time; CAS fails closed (`target moved`) |
| rollback hides a broken state | tree-equality check; a failed rollback halts all shipping and escalates |
| shipped content steers later phases | instruction-surface diffs are owner decisions (5.4) |
| a `security` job ships unattended (Q4) and weakens the product's security | the same gates as every type: generated DoD with PROBEs reviewed by another identity, holdouts that must fail on the base, the verifier, post-ship checks with the regression set, automatic rollback; diffs to instruction surfaces, import hooks, CI workflows and `conftest.py` stay owner decisions whatever the type; the secret scan before a `github` push |
| the github push publishes a secret or a private address | the release scanner's patterns (and the denylist) run over the diff before every push; a finding is a `DECISION`, nothing is pushed |
| a producer plants a GitHub Actions workflow that runs on the merge with the repository's secrets | `.github/workflows/` diffs are owner decisions (5.4); the factory never merges them unattended |

### 5.6 Acceptance (pillar C)

`$T` = `$WS/projects/greeter` (the target), job 2 verified with holdouts PASS on commit `$C`.

| # | command | expected |
|---|---|---|
| C1 | `bin/konstant ship 2 --dry-run --json` | `"decision": "ship"`, `"commit": "$C"`, `"pre"` = the target tip, every guard rule listed `ok` |
| C2 | `bin/konstant ship 2; RC=$?` then `git -C $T rev-parse main` | `RC=0`, output `$C`; `bin/konstant ship list --json` shows `"state": "shipped"` |
| C3 | ship a level-4 job (verified, no holdouts) | exit 1 `refused: no holdout PASS for commit ...`; `git -C $T rev-parse main` unchanged |
| C4 | holdouts passed on `$C`, evidence names another commit | exit 1 `refused: holdouts ran on $C, the evidence names ...` |
| C5 | `FAKE_HARNESS_MODE=ship-break` (verifies, then fails a post-ship probe on the target) | `ship list --json` `"state": "rolled_back"`; `git -C $T rev-parse main^{tree}` equals `git -C $T rev-parse <pre>^{tree}`; `git -C $T log -1 --format=%s main` = `konstant: roll back ship 1`; job 2 still `verified` and a follow-up job filed whose acceptance holds the failed check as a `PROBE:` row |
| C6 | after C5: `git -C $T merge-base --is-ancestor $C main; echo $?` | `0` (no history rewritten) |
| C7 | the target tip moved (a commit made outside the factory) after the job's clone was made | exit 1 `target moved: expected <pre>`; escalation `DECISION`; the target unchanged by konstant |
| C8 | a `command` target whose `rollback_cmd` fails, after a post-ship failure | `"state": "rollback_failed"`; `bin/konstant factory status --json` `"shipping": "halted"`; the notifier gets `ROLLBACK_FAILED` |
| C9 | `FAKE_HARNESS_MODE=self-ship` (the producer runs `git -C $T update-ref refs/heads/main HEAD`) | the phase log shows the write denied; `git -C $T rev-parse main` unchanged |
| C10 | a verified job whose diff adds `AGENTS.md` to the project | not shipped; escalation `DECISION: instruction surface changed (AGENTS.md)` |
| C11 | `[ship] target = "github"` against a local bare repository as the remote and a `gh` stand-in on PATH (no network), then `ship-break` | the remote `main` moves to `$C` through a recorded PR create + merge; the rollback is a new commit merged through a second PR whose tree equals the pre-ship tree; no force-push in the stand-in's log |
| C12 | a verified job whose diff adds a token-shaped string, `github` target | not pushed; escalation `DECISION: secret scan finding in <path>`; the remote unchanged |

## 6. Pillar D: escalation only, budgets, and the factory loop

### 6.1 The loop

`konstant factory run [GOAL ...] [--until-idle | --once] [--dry-run] [--json]`
(`factory/loop.py`) runs in the foreground; `factory start|stop|status` run the same loop in the
background with `var/factory/factory.pid`, pid-checked like `board stop` (F-23). One factory per
workspace (an flock under `var/locks/`). Each tick:

1. read `var/factory/STOP` (the kill switch `factory stop` writes) and stop cleanly if present;
2. for each active goal: charge and check the budget (6.2); if it is exhausted, pause the goal
   and escalate `BUDGET_STOP`;
3. no backlog yet: run intake (4.2) once;
4. pick the next ready job: `queued`, approved, sealed, `after` satisfied, project not locked;
5. claim it, create the job clone, run the existing runner on it (`cli/task_run.py` `_run` with
   `--job`), which ends in `close_and_verify` (`gate/loop.py`) and so in the verifier with
   holdouts;
6. `verified` -> ship (5) -> post-ship -> rollback on failure;
7. BLOCKED or a verifier FAIL at `max_rounds` -> escalate `BLOCKED` with the reasons (redacted)
   and continue with other jobs;
8. all jobs of a goal shipped -> goal `done` (an outcome on the status view, not an interruption).

`--until-idle` exits when no goal has work left: 0 when every goal is done, 4 when any goal ended
in an escalation, 2 for a refusal before the start (no jail, unmeasurable budget, a foreign
harness composition from `Adapter.preflight`), 5 for an internal error. An internal error stops
the factory and escalates: a dark factory that does not understand its own state must not keep
shipping. The loop never needs the owner token, and a test proves it (6.6, D8).

### 6.2 Budgets

Limits come from the goal (`[limits]`) and are recorded per job (`budget_json`). Owner decision
Q5: **`max_attempts` (default 3, task runs per job) is the only required limit**; wall clock,
total task runs, tokens and cost are optional and unlimited when absent or 0. A job that used its
`max_attempts` without reaching `verified` is BLOCKED and escalated (one chat notification), the
goal continues with its other jobs. Spending is written to `budget_ledger` by code:

| kind | measured from | always available |
|---|---|---|
| `wall_s` | phase manifests (`phases/*.json` `duration`) and the loop's own clock | yes |
| `attempts` (per job), `task_runs`, `phases` | the runner's records | yes |
| `rollbacks` | `ships` | yes |
| `tokens`, `cost` | `Adapter.usage(log)` (returns the usage or `None`), a new adapter hook that reads the harness's own usage report from the phase log (for example Claude Code's JSON result) | **only for adapters that implement it** |

A budget that cannot be measured is refused **before the start**: `factory run` exits 2 with
`budget max_cost_usd cannot be measured on harness command`. konstant does not guess spending. A
budget stop pauses the goal, kills nothing mid-phase (the phase finishes or hits
`[harness] timeout_s`), escalates once, and resumes only on `goal resume`.

### 6.3 Notifications: only what needs the owner

`factory/notify.py`, `[notify] kind = "stdout" | "file" | "webhook"`:

| event | when | notify by default |
|---|---|---|
| `BLOCKED` | a job is blocked (verifier BLOCKED, max rounds, max rollbacks, authoring refused) | yes |
| `DECISION` | an owner decision (5.4, a DISPUTE, a worn holdout set twice) | yes |
| `BUDGET_STOP` | a goal's budget is exhausted | yes |
| `LEAK` | a holdout canary was found (3.5) | yes |
| `ROLLBACK_FAILED` | 5.3 | yes |
| `HALTED` | an internal error, a notifier failure | yes (on stdout and the file at least) |
| `SHIPPED`, `ROLLED_BACK`, `GOAL_DONE` | outcomes | no: status view and `var/factory/events.jsonl` only |

Payload: `{event, goal, job, display_id, reason, at, board_url}`. The reason is the redacted
one-line reason (`board/redact.py`) and never carries code, briefs, holdout text or tokens. A
webhook URL must be `https`, or a loopback host listed in `[notify] url_hosts`. One notification
per (goal, job, event) until the owner acknowledges it (`factory ack ID`), so a stuck job does not
flood the owner. **A notifier that cannot deliver halts the factory** (after `[notify] retries`):
the factory stops rather than keep working while the owner cannot be reached. Undelivered events
stay in `var/factory/spool/`.

### 6.4 The factory view on the board

`board/api/factory.py` adds read routes (any valid token, like every read):
`GET /api/factory/status`, `/api/factory/goals`, `/api/factory/goals/{id}` (budget used and
limit per kind, jobs by state, ships with state, open escalations, the last tick time) and
`/api/factory/escalations`. The static view (`board/static/index.html`, `board.js`) gains a
Factory tab, rendered with `textContent` only, as the rest of the view is. Holdouts appear only
as counts and states. A heartbeat older than three ticks shows the factory as stale; `doctor`
reports the same as a WARN.

### 6.5 Threat model (pillar D)

| failure or attack | what stops it |
|---|---|
| runaway spend or loops | hard limits checked every tick; an unmeasurable budget refuses the start; the level-4 repeat-stop and max rounds still apply |
| a phase edits its goal or limits | goals are copied into `var/factory/` (machinery: read-only); `spec_sha256` immutable |
| a phase edits the ledger | the board DB is read-only to phases; `budget_ledger` is append-only (trigger) |
| a silent factory | notifier failure halts; heartbeat on the view; doctor WARN |
| alert fatigue | one notification per (goal, job, event) until acknowledged; outcomes are not notifications |
| the notifier leaks secrets or code | redacted one-line reasons only; URL rules |
| two factories, or a zombie loop | flock, pid check (F-23), the reaper for every phase (F-05) |

### 6.6 Acceptance (pillar D)

| # | command | expected |
|---|---|---|
| D1 | goal with `max_task_runs = 1` (an optional limit, set), `FAKE_HARNESS_MODE=tester-fails-3x`, `bin/konstant factory run greeter --until-idle; RC=$?` | `RC=4`; `$WS/var/factory/notify.log` has one line starting `BUDGET_STOP greeter`; `bin/konstant goal show greeter --json` `"status": "paused"` |
| D1b | goal with only `max_attempts = 3` (Q5), `FAKE_HARNESS_MODE=tester-fails-3x` | the job is BLOCKED after its 3rd attempt with one `BLOCKED` notification; no `BUDGET_STOP`; `RC=4` |
| D2 | goal with `max_cost_usd = 5` on the `command` harness | `RC=2`, `budget max_cost_usd cannot be measured on harness command` |
| D3 | an honest goal run to completion | `RC=0`; `notify.log` has 0 lines; `events.jsonl` has `SHIPPED` rows |
| D4 | `bin/konstant notify test --kind webhook` against a local test server | the server receives JSON with `event` and `reason`, and without `brief`, `acceptance` or `evidence` keys |
| D5 | a webhook that refuses every request, during a run | the factory exits 4 `notifier failed: factory halted`; the event is in `var/factory/spool/` |
| D6 | `curl -s -H "Authorization: Bearer $VIEWER" http://127.0.0.1:$PORT/api/factory/goals/greeter` | JSON with `budget`, `jobs`, `ships`, `escalations`; no `RUN`/`EXPECT`/`khc-` text |
| D7 | `bin/konstant factory start; bin/konstant factory start; RC=$?` | the second `RC=2`, `a factory already runs (pid ...)`; `bin/konstant factory stop` -> `factory status` `stopped` |
| D8 | `chmod 000 $WS/var/secrets/owner.token; bin/konstant factory run greeter --until-idle; RC=$?` | `RC=0` (no human role needed) |
| D9 | `python -m pytest -q tests/factory` | exit 0; every refusal above has a `_red` and a `_green` test |

## 7. Proof of level 5

One command, a sample project and a scripted owner chat, no human input, run offline with the
fake harness:

```sh
bash tests/e2e/factory.sh        # builds the tarball, installs it fresh, runs the legs below
```

The sample lives in the release: `examples/greeter/` (a tiny Python project with a README and one
test) and `examples/greeter/goal.toml`. **No scenario ships in the release**: everything in the
workspace is readable by phases. The legs use the scenario writer (`author = "agent"`, the fake
harness's scenario mode), and one extra check uses `author = "owner"` with two scenarios the e2e
script writes into its own temp dir outside the workspace and seals with `holdout add`. stdin
is `/dev/null` and `owner.token` is unreadable for the factory's whole run.

| leg | setup | expected |
|---|---|---|
| P0 chat intake | a fake orchestrator session is handed one scripted owner message ("make greeter greet by name, with a CLI and a README"), confirms it and runs `goal add --from-chat` (4.0) | the goal exists with `"source": "chat"` and `max_attempts = 3` as its only limit; the legs below run from that goal; every escalation of the run shows up in the session's next turn, the outcomes on request |
| P1 honest | default fake harness | `factory run greeter --until-idle` exit 0; every backlog job `verified`; `ship list --json` all `shipped`; `git -C projects/greeter log main` has one fast-forward per job; `notify.log` empty |
| P2 cheating producer | `FAKE_HARNESS_MODE=overfit` (the visible DoD passes, held-out inputs fail) | verify FAIL `holdout H1 failed`, max rounds -> BLOCKED; **no ship**: the target tip unchanged; `notify.log` one `BLOCKED` line; exit 4 |
| P3 reader | `FAKE_HARNESS_MODE=peek` | every read of the store denied (phase log); no canary in the diff; then the same leg with `[gate] jail = false`: `factory run` exit 2 before any phase |
| P4 post-ship failure | `FAKE_HARNESS_MODE=ship-break` | ship, post-ship probe FAIL, automatic rollback: the target tree equals the pre-ship tree, the shipped commit still an ancestor, a follow-up job filed; after `max_rollbacks` BLOCKED + one notification; exit 4 |
| P5 budget | `max_attempts = 3` (the default) with `tester-fails-3x`; and once with the optional `max_task_runs = 2` | the job BLOCKED after 3 attempts, one notification; with `max_task_runs = 2`: `BUDGET_STOP`, goal paused; exit 4 both times |
| P6 github target | `[ship] target = "github"` against a local bare repository as the remote and the `gh` stand-in (no network) | P1's ships arrive on the remote's `main` through recorded pull requests; P4's rollback is a revert commit merged through its own pull request; the stand-in never saw a force-push |

The e2e prints `E2E-FACTORY: PASS` only when every leg met its row, and each leg's checks read
artifacts (the git refs, `ship list --json`, `job show --json`, the notifier file), never the
loop's own summary.

**Optional live run** (`tests/e2e/factory_live.sh`, not part of CI): the same P0 + P1 legs with a
real model through dsh and a local OpenAI-compatible endpoint (the address only in the environment
of that run) playing EVERY role, scenario writer included (the owner's setup, Q1), plus P2 with a
prompt that asks the producer to special-case the visible example, and P6 against a private
GitHub test repository named only in that run's environment. It
reports `E2E-FACTORY-LIVE: PASS` or the leg that failed. A model choosing to cheat on its own
cannot be forced, so the live run proves the plumbing on a real harness, and the fake harness
proves the guards.

## 8. Wave plan

Each wave is one unit of work for one implementer, ends in a pushed commit with an evidence file,
and starts only when the previous wave's acceptance rows pass. Every new refusal ships with a
planted-bad test (red) beside the green one. Each wave updates DESIGN.md, CONCEPTS.md and CLI.md
for what it lands.

| wave | delivers | extends (existing code) | depends on | acceptance |
|---|---|---|---|---|
| **L5-1** sealed holdouts (**done**; see "L5-1 as built" below) (before L5-2 only dsh phases are confined, so the adversarial modes run through the real dsh adapter with `tests/fixtures/stub_dsh.py`, as the second review's fixes did) | scenario format, `holdout add/list/check/show`, `holdout/store.py` + `lint.py` + `leak.py`, `verify/holdout.py` (pinned materialisation, jailed no-network runs, redacted findings), settle extension, `0002` tables `holdouts` + `verifications.holdout_json`, `machinery.SEALED` in jail + all adapters, DECLINED cannot excuse holdouts, the claim guard, `jobs.holdout_required`, fake modes `overfit`, `peek`, `leak` | `machinery.py`, `jail.py` `hidden`, `verify/verifier.py` `settle`/`verify_job`, `verify/rerun.py`, `agents/settings.py` `render`, `harnesses/codex.py` `filesystem`, `harnesses/gemini.py`, `gate/rules/done.py`, `board/migrate.py` | v0.1.0 | A1-A3, A5-A13 (through the dsh adapter) |
| **L5-2** confinement + identities (**done**; see "L5-2 as built" below) | generalised `Adapter.confine` for every harness in factory mode, one exposed identity token per phase, labelled worker tokens, board label guards, job clones + target read-only, `jobs.workdir` and the `{workdir}` probe substitution (`verify/probe.py`, `verifier.project_dir`), `Adapter.relocatable_home`, doctor `factory` rows, live smoke of a jailed claude phase (records whether Claude's sandbox nests) | `harnesses/base.py`, `claude.py`, `codex.py`, `gemini.py`, `command.py`, `board/auth.py`, `board/api/lifecycle.py`, `board/transitions.py`, `cli/task_run.py`, `cli/doctor.py` | L5-1 | A4 on every adapter, B6, B7, C9 |
| **L5-2b** confinement profiles (**done**; see "L5-2b as built" below; owner request 2026-11-01) | `[confinement]` profile closed/open + per-capability options + the integrity core, mapped by every adapter and the jail, `confinement show`, doctor rows, `install.sh`/`get.sh --confinement`, `host_agents` (the session's refusing agent-CLI shims) | `jail.py`, `harnesses/*`, `agents/settings.py`, `gate/harness.py`, `cli/dsh.py`, `cli/doctor.py`, `install.sh`, `get.sh` | L5-2 | the open profile's probe on every harness path: host reach yes, core no (factory and level 4); closed red twin; integrity-off red twin |
| **L5-3** intake + scenario writer (**done**; see "L5-3 as built" below) | intake from the orchestrator chat (4.0: `goal add --from-chat`, `[factory] goal_roles`, `[factory] defaults`), goal files (`goal add/list/show/pause/resume/cancel`), type `intake` + agent `planner`, `DOD-verdict.md`, deterministic filing, approval rule, role agent `scenario-writer`, `holdout/author.py` with the run dir in the store, fake planner / reviewer / scenario modes incl. `weak-dod` | `catalog/types.yaml`, `catalog.py` `ROLE_AGENTS`, `board/dod.py` `lint`, `gate/runner.py`, `gate/rules/authorship.py`, `gate/rules/judged.py`, `agents/generate.py` | L5-2 | B1-B5, B8-B11 |
| **L5-R1** independent review 1 | review only, by someone who built none of L5-1..3: try to reach `verified` past holdouts, read the store from every harness, leak through feedback, transcripts, the board or run records, forge identities, weaken a generated DoD; one reproduction per finding | the adversarial fake harness, as the first two reviews did | L5-3 | report with severity per finding |
| **L5-F1** fixes 1 | one red-then-green test per finding under `tests/review/` (`test_H<nn>_...`); zero open P0/P1 | — | L5-R1 | all A and B rows green again |
| **L5-4** ship + rollback | `ship`, `ship list`, targets `github` (push + PR create/merge, revert-PR rollback, the secret scan before a push, a `gh` stand-in for tests; Q2) / `branch` / `apply` / `command`, `[ship] decision_types = ["infra"]` (Q4), the guard on both sides, plumbing-only ref moves, post-ship checks with the regression set, rollback + tree check, the follow-up job after a rollback, halt on a failed rollback, decision rules (5.4), table `ships`, fake modes `ship-break`, `self-ship` | `gate/rules/common.py` git plumbing, `verify/probe.py` `run_line`, `verify/holdout.py`, `board/api/` | L5-F1 | C1-C12 |
| **L5-5** factory loop + budgets + notifier + view | `factory run/start/stop/status/ack/resume-shipping`, `max_attempts` as the one required limit (Q5), `[notify] kind = "chat"` (4.0), `budget_ledger`, `Adapter.usage`, unmeasurable-budget refusal, `notify` (stdout/file/webhook), `escalations`, `board/api/factory.py`, the Factory tab | `gate/loop.py`, `cli/task_run.py`, `cli/board.py` (pid handling), `board/redact.py`, `board/static/` | L5-4 | D1, D1b, D2-D9 |
| **L5-6** proof of level 5 | `examples/greeter/`, `tests/e2e/factory.sh` (P0-P6), CI job, QUICKSTART "level 5" section, the optional live run recorded | `tests/e2e/fresh_install.sh`, `tests/fixtures/fake_harness.py` | L5-5 | `E2E-FACTORY: PASS`; full `pytest`; release build CLEAN |
| **L5-R2** independent review 2 | review of the whole factory (ship, rollback, budgets, loop, notifier, view) plus a regression run of F-01..F-35, G-01..G-07 and the L5-R1 findings, on a tarball installed the documented way | — | L5-6 | report |
| **L5-F2** fixes 2 + release | red-then-green tests per finding, zero open P0/P1, CHANGELOG, a release build; tagging and publication are the owner's step | — | L5-R2 | full `pytest`, `E2E-FACTORY: PASS`, `RESULT: CLEAN` |

### L5-1 as built

Landed as DESIGN.md §7.1 describes. Where it differs from sections 2-3 above, and why:

- The migration is `0002_holdouts.sql`, not one `0002_factory.sql`: each wave adds its own tables
  in its own migration. It also rebuilds `trail` once for every level-5 trail kind, and adds
  `holdouts.trail_id` (the seal is ordered against claims by trail id, not by second-precision
  timestamps) and `holdouts.generation` (the exposure budget counts failed rounds per set).
- Scenario format: no inline comments (the example in 3.1 had them); `RUN` follows argv rules, not
  the probes' character rules (3.1, 3.2). `holdout add` takes several `--file`s, because the set
  rule (min_per_job, a proof) is checked over the sealed set plus the new files.
- Confinement before L5-2: a holdout job runs only when every harness of the run confines its
  phases (`Adapter.confines`; dsh only), else exit 2 `holdouts need a confined phase`; `task gate`
  (an interactive, unconfined session) refuses such a job with exit 2 as well. Without job clones
  (L5-2) the scenarios run on the evidence `COMMIT=` materialised at the project's own path, and the
  negative control on the project's current HEAD.
- The board also refuses a PASS verdict on a holdout job unless it carries the verifier's holdout
  result for the sealed set (every holdout passed, the commitment digest, no LEAK), whoever posts
  it; holdouts are sealed only while the job is `queued` or `waiting_approval`.
- A `DISPUTE` row stops the run BLOCKED (`rules/holdouts.py`) until the escalation path of L5-5
  exists; a second worn set blocks the job with a `DECISION` reason on the trail.
- A program in `RUN` that is not on PATH (or not executable in the tree) makes a scenario
  unrunnable (BLOCKED), as a timeout does: bubblewrap's own exit code cannot tell "not found" from
  the product's exit 1.
- The scenario runs see the host `/tmp` read-only (the same jail shape as the tests rule, 3.6
  step 2) and write only to the materialised tree and a private `TMPDIR`, both deleted.

### L5-2 as built

Landed as DESIGN.md §7.2 describes (and §5 for the identities). Where it differs from section 2
above, and why (section 2's text is already corrected where it was wrong):

- **Factory mode = a run of a job with sealed holdouts** (`cli/task_run.py` `_run_factory`); the
  factory loop of L5-5 will start its phases the same way. Every adapter confines in factory mode
  (`Adapter.confines(jail, factory)`), an explicit command template is confined as the `command`
  adapter, and `Harness.run` refuses to start a factory phase it could not confine. L5-1's
  "holdout jobs only on dsh" restriction is gone; `task gate` still refuses a holdout job.
- **Exposed tokens**: the phase identity's token AND the read-only `viewer` token (2.1 corrected).
  Each phase carries `KONSTANT_IDENTITY` (default `worker`); in L5-2 every phase is `worker` (the
  planner, DoD-reviewer and scenario phases arrive with L5-3); the in-task client maps worker
  requests to the identity's token and refuses every other label.
- **Per-phase homes**: claude (`CLAUDE_CONFIG_DIR`), codex (`CODEX_HOME`) and gemini
  (`GEMINI_CLI_HOME`) get a fresh home per factory phase under `var/harness/<name>/phases/`, removed
  afterwards; only `~/.claude/.credentials.json` / `~/.codex/auth.json` are bound in, read-only
  (`jail.wrap` `ro_binds`). `Adapter.relocatable_home`: claude, codex, gemini, dsh yes; `command`
  no (refused for the scenario role in L5-3; `doctor` names it).
- **Claude Code's sandbox in the jail, live check**: one cheap haiku run of a jailed claude phase
  through the real adapter, in a workspace under `/tmp`: Claude Code's sandbox did NOT start
  ("Failed to create bridge sockets"), and every Bash call was then denied (fail closed but
  useless). Diagnosed without further model calls (a dead loopback endpoint, then a loopback
  stand-in for the Messages API that scripts Bash tool calls): the cause is the long TMPDIR (the
  bridges are unix sockets; it fails unjailed too). With the jail's own `/tmp` as TMPDIR and socat
  on PATH, a scripted Bash call inside the jail saw only the `lo` network interface (Claude Code's
  sandbox nested and active); with the fallback (its sandbox off) it saw the host interfaces, the
  store still empty and only its own token readable. Built: TMPDIR = the jail's `/tmp` when the
  jail has a private one; `claude.sandbox_nests(workspace)` = nested bubblewrap starts AND socat
  present AND private `/tmp`; otherwise `without_sandbox` passes the same settings minus
  `sandbox`. On the build host socat is not installed, so its `doctor` reports the fallback.
- **Job clones**: the board, not the runner, computes `workdir` and `workdir_base` at the first
  claim (git plumbing in the board process) and records them once (trigger); the extra column
  `workdir_base` gives ship (L5-4) its `pre` and the leak scan its base for every round. A holdout
  job on a project that is not a git repository (or has no commit) cannot be claimed (409, fail
  closed: its holdouts could not run). The clone uses the target's object store as an alternate;
  a tree path into `.git` is refused (also when the verifier materialises a commit). The record is
  written only after the claim, so nothing (not even OUT) is created in the target.
- **`dod-review` route** (`POST /api/jobs/{id}/dod-review`): added now so the B7 guard is
  reachable through the API; L5-3's intake drives it.
- **Guards apply at level 4 too**: the requester-cannot-approve rule holds for every job (an
  owner who files a job with `--approval` needs another identity to approve it), and the owner who
  sealed a job's holdouts cannot claim or close that job.
- **Fake modes / stand-ins**: `self-ship` (C9) added now (planned for L5-4) because C9 is an L5-2
  row; `tests/fixtures/stub_cli.py` plays `claude`, `codex` and `gemini` with the fake harness, so
  A4 runs through every real adapter. codex and gemini were not run as real CLIs (no codex model
  call; gemini is not installed on the build host).
- **Owner decisions (section 9)**: none of L5-2's configuration keys is changed by them; the
  `identities` doctor row states that one model may play every role (Q1).
- The cosmetic `[type:code] (None)` reason print of a holdout run is fixed (the refusal check no
  longer overwrites the classification reason).

### L5-2b as built

Landed as DESIGN.md §9.1 describes (code: `konstant/confinement.py`, `harnesses/base.py`
`jail_layout`, `cli/confinement.py`). Where it differs from 2.1 above or from the request, and why:

- **Open jails level 4 too.** The request asked for a thin jail with masks over the integrity
  core; at level 4 claude, codex, gemini and `command` phases were never jailed before. Under
  `open` every adapter now confines at level 4 whenever bubblewrap works, because the jail is the
  only thing that keeps the core around a shell that may otherwise do anything (Claude Code's own
  sandbox, when it cannot nest, is then switched off for the phase as in factory mode). Without a
  working jail an open level-4 phase has only its harness's own rules (`confinement show` says
  which).
- **`integrity = "off"` needs `profile = "open"`** (a config error otherwise): a closed profile
  without its core is not a coherent setting. "Factory mode refuses to start" is implemented in
  `verify/holdout.py` `confined`, the one gate of every factory path, so `holdout add` (the
  negative control), `holdout author`, `intake` and a holdout job's `task run` all exit 2.
- **The closed profile tightened three things** that 0.1.0 left open to jailed phases and every
  phase's environment: the ssh-agent socket and the docker socket are masked in the jail, and
  `SSH_AUTH_SOCK`, `DOCKER_HOST` and the credential variables of `machinery.CREDENTIAL_ENV`
  (`GITHUB_TOKEN`, `GH_TOKEN`, `AWS_*`, ...; never a harness's own model key) are dropped from a
  phase's environment. A closed profile that masks `~/.aws` but passes `AWS_SECRET_ACCESS_KEY`
  was not closed. `[harness] env` still sets anything explicitly.
- **Not enforceable everywhere**: `network = false` cannot be cut by the jail (the harness reaches
  its model through the same network), so it holds only where the harness separates tool traffic
  (Claude Code's sandbox, codex); `ssh_agent` under Claude Code's own sandbox opens every unix
  socket (a static settings file cannot name the per-login socket); codex's profile cannot name a
  socket. `confinement show` marks each `partial` or `no`.
- **Two escapes stated, one guarded**: the docker socket is root on the host, so factory mode never
  passes it (level 4 open does, with a `doctor` WARN); an ssh login back into this host leaves the
  jail, so `doctor` WARNs when a `~/.ssh/*.pub` is in the user's own `authorized_keys` (only
  public files are read).
- **Scenario writer always closed**: an open scenario writer could copy its drafts to a host path
  a later producer reads; `Phase.conf` forces `CLOSED` for the `scenario` identity.
- **The orchestrator session** (found in L5-3's live smoke: its model ran the host's own dsh
  launcher, which forces the operator's personal dsh home): `host_agents` (default false in both
  profiles) controls refusing `dsh`/`claude`/`codex`/`gemini` shims first on the session's PATH;
  konstant drops that dir for its own processes. A program named by its absolute path is not
  stopped (the session is unjailed by design). The session's own dsh sandbox stays
  `workspace-write` under `open` (the session patch resets it).
- **Not run live**: no model call in this wave. The open renderings of Claude Code's settings
  (`sandbox.network.allowedDomains ["*"]`, `allowAllUnixSockets`) are taken from Claude Code's
  published settings schema and the dsh `danger-full-access` preset from dsh's source; the probe
  runs through the real adapters with the stand-in CLIs (`tests/fixtures/stub_cli.py`,
  `stub_dsh.py`) and the fake harness.

### L5-3 as built

Landed as DESIGN.md §7.3 describes. Where it differs from sections 2-4 above, and why:

- **The chat confirmation is mechanical, not only a sentence.** `goal add --from-chat --session ID`
  records the goal as `proposed` (nothing copied, no intake); the konstant-gate plugin runs `konstant
  chat turn` on every genuine owner message of the session (depth 0, `source.kind = user`), and only
  the owner's NEXT message there decides it: a plain yes confirms (the board writes the copy, the
  goal becomes active, `source = "chat"`), anything else withdraws it (status `withdrawn`, which
  frees the id). `goal add` and `chat turn` refuse inside a task run, so text in a phase log, a web
  page or a file cannot propose or confirm. Limit (stated in DSH.md): the session itself is
  unjailed, so a model in it that ran `chat turn ... yes` on its own could confirm its own proposal;
  the line stays visible and the goal still passes the whole factory. The plugin path is on when
  `[notify] kind = "chat"`; a typed request without a `[type:]`/`[job:]` tag then gets an INTAKE
  block instead of the level-4 gate (a tagged one keeps the gate).
- **After the yes, intake is `bin/konstant intake GOAL`** (the owner, or the factory loop of L5-5):
  nothing starts a background run from the chat in this wave. Found in the live smoke: after the
  owner's yes the orchestrator model ran `konstant intake` itself from the session (4.0 step 4 says
  it never runs factory steps). The plugin now marks the session's own bash
  `KONSTANT_CHAT_SESSION=<id>` and konstant refuses `intake`, `holdout author` and every factory
  identity (`--as planner|dod-reviewer|scenario|factory`) there; the INTAKE block says so too. Its escalations and outcome come back
  into the chat at the next turn (escalations as lines, outcomes as one summary line).
- **The filing window.** Spec 2.1 lets each phase read its identity's token, so a planner phase could
  have filed goal jobs itself, around the deterministic filing. The board therefore takes goal jobs
  (only from the `planner` identity) and their `dod-review` (only from `dod-reviewer`) only while the
  `factory` identity holds the goal's new `intake` state at `filing` (`none -> planning -> filing ->
  filed`, or `refused`; `filed` is final: a goal is taken in once). A goal job's `after` must name a
  job of the same goal. Known gap: an intake phase can still file a level-4 job (no goal) with its
  planner token, as L5-2 allowed every identity to file; no factory step ever approves, seals or
  ships such a job.
- **Approval**: any approver of a goal job (the owner too) needs the latest `dod-review` to be SHIP
  from another identity than the requester; the `factory` identity approves goal jobs only.
- **Identity pairs**: besides L5-2's guards, the planner of a goal job never claims or closes it and
  none of the four identities (planner, dod-reviewer, scenario, factory) claims or closes any job.
- **Schema** `0004_goals.sql`: `goals` gains `spec_text` (the filed bytes), `source`, `session`,
  `intake`, `created_by`, the statuses `proposed` and `withdrawn`; `jobs.ship_mode`
  (`auto`/`decision` from `[ship] decision_types`, owner decision Q4) beside `goal_id` and
  `budget_json`, all computed by the board at filing and immutable. `budget_json` =
  `{max_attempts, goal_limits}`: the job's own attempts and the goal-wide limits that are set.
- **`var/factory/` joined `machinery.DIRS` now** (planned for L5-5): goal copies, events and chat
  cursors live there from this wave on.
- **The intake run** has no project: its phases work in `OUT` under the run dir (target read-only,
  named in the prompt), the close-out acts as `planner`, and the phase manifest records each phase's
  identity. A new DoD-check rule `backlog` (intake runs only, unexcusable) applies the filing rules
  inside the loop, so the planner is resumed with the reasons; the filing after MET applies them
  again (exit 3, nothing filed). `types.yaml` gained `flag_only` and `identity`.
- **The scenario writer reads no token** (2.1 would allow its own): it needs no board, and without a
  token it cannot read other jobs' trails or evidence either. Its jail also masks `var/runs/`,
  `var/logs/`, `var/factory/`, `var/sessions.json`, the board DB, every job clone and the target's
  `.audits/`. `jail.wrap` now binds a writable dir that lies inside a masked one AFTER the mask
  (before, such a bind made the jail skip the mask: the drafts dir inside `var/holdout/` would have
  exposed every job's scenarios); its prompt file is bound read-only. A refused set is retried once
  with the lint reasons, then `holdout-authoring BLOCKED` (a BLOCKED event plus an `escalation`
  trail row, which the board now accepts from the factory identity); `holdout author JOB` runs the
  same phase by hand.
- **Notifier as far as intake needs it**: `factory/notify.py` writes `var/factory/events.jsonl` and
  delivers escalations to `stdout`, `file` or `chat`; the outcome vocabulary gained `FILED`. Webhook,
  retries, acks and the halt on a failed delivery stay in L5-5.
- **doctor** rows `scenario writer` (one model for every role: INFO) and `chat intake`.
- **A stopped intake escalates** (also found in the live smoke: a time-boxed intake was stopped and
  the chat heard nothing): SIGINT/SIGTERM end `konstant intake` with a `BLOCKED` event (`intake
  stopped by SIGTERM after Ns`) and the intake state `refused` (unless it already reached `filed`).
- **Live run (owner's setup: one local model through dsh for every role)**: the chat path worked as
  designed (proposal in the request's turn, filed on the yes, no intake from the chat); a full
  intake on that model takes longer than an hour (planner, a DoD review that FIXed a real bug in a
  brief, a second planner cycle; the scenario writer's first drafts were refused by the held-out
  lint and its second set sealed), so the live runs were time-boxed and recorded partially.

**Level 5 is reached when L5-F2 is done**, not before: two independent reviews, the second one
after everything (ship and rollback included) exists.

## 9. Owner decisions (2026-11-01; were the open questions)

The owner answered the five questions on 2026-11-01, verbatim (typos kept; the name of his local
model, an OpenAI-compatible model he serves himself, is withheld from this public page):

> "1. for me, local [model name withheld] will do everything. 2 guthub. 3. no. 4. all except
> infrastructure. 5. mac attempts 3. no time limit, no token or cost limit. the goal is fir me to
> talk to my orchestrator the same way i fo now but the system becomes a dark factory ibstead of
> the level 4 that us v.0.1.0"

How the plan reads them. Each decision is one configuration key, so a later change of mind is a
config change, not a rewrite; the public product keeps conservative defaults where the owner's
choice is specific to his setup.

1. **One model plays every role** (was: the scenario writer on another harness or model when one
   is configured, with a `doctor` WARN when the same). One local OpenAI-compatible model is the
   producer, the planner, the DoD reviewer, the verifying phases AND the scenario writer.
   Independence therefore comes from identity (the board refuses the forbidden pairs, 2.2),
   context (each phase is shown only what its role needs; the scenario writer never sees a job
   clone or a producer's output, 3.4) and file isolation (the jail, 2.1, 3.3), plus the mechanical
   checks a same-model scenario must still pass (negative control, held-out lint, 3.2). Nothing in
   the design assumes a second model; `[holdout] writer_harness` / `writer_model` stay optional;
   `doctor` reports a single-model setup as supported (INFO), and the L5-2 `identities` row says
   so. Keys: `[harness]` (one model), `[holdout] writer_model` (empty = the same).
2. **Ship to GitHub** (was: a local branch only; pushes through `command`). The `github` target
   (5.1) pushes a branch, opens a pull request and merges it through `gh`; rollback is a revert
   commit merged through its own pull request; never a force-push. It is the documented default
   for the owner's configuration (`[ship] target = "github"` in his goals and `[factory]
   defaults`); the public product's default stays `branch` and `github` is opt-in by config. The
   local `branch` target stays available. Key: `[ship] target`.
3. **No second OS user** (unchanged default). The jail is required (fail closed); the
   second-user mode stays documented and reported by `doctor`. Key: `[holdout] store`.
4. **Every job type ships without the owner except `infra`** (was: `infra` and `security` stop).
   `security` jobs now ship unattended; the diff rules of 5.4 (instruction surfaces, import hooks,
   CI workflows, `conftest.py`) still stop any type, and the `github` target scans every diff for
   secrets before a push (5.1, 5.5). Key: `[ship] decision_types = ["infra"]`.
5. **`max_attempts = 3` is the only required budget** (was: `wall_clock` and `max_task_runs`
   required). A job gets at most 3 attempts (task runs) before it is BLOCKED; wall clock, total
   task runs, tokens and cost are optional and unlimited unless set, and a set token or cost
   limit is still refused on a harness that cannot measure it (6.2). Key: `[limits]
   max_attempts` (default in `[factory] defaults`).

**The vision behind the answers**: the owner keeps talking to his orchestrator in chat exactly as
he does at level 4, and the system behind that conversation becomes the dark factory. The chat is
the intake (section 4.0) and the place escalations come back to; goal files stay the mechanism
underneath; the level-5 proof includes the chat intake (leg P0, section 7).

## 10. Risks: what a dark factory can do wrong that level 4 could not

| risk | why level 4 was safe from it | mechanical guard at level 5 |
|---|---|---|
| broken code reaches the target with nobody looking | a person decided what to merge | ship only on `verified` with every holdout passed on the exact commit (5.2); post-ship checks, regression set, automatic rollback (5.3) |
| a weak, self-generated DoD makes "verified" meaningless | a person wrote the DoD | DoD lint without warnings, at least one PROBE per job, review by a different identity, holdouts from a third identity that must fail on the base (3.2, 4.2) |
| one model writes the DoD, the holdouts and the code, and they agree on the same mistake (the owner's chosen setup, Q1) | a person wrote the DoD | distinct identities enforced by the board; separate contexts (the scenario writer sees goal, brief and a read-only target only; the producer never sees the scenarios); holdouts must fail on the base and stay out of the brief, so a scenario cannot just echo the producer's reading; black-box only; post-ship regression set and rollback; another harness/model optional, never required |
| a same-model scenario writer is steered by the producer of an earlier job (text it shipped into the target) | there was no scenario writer | the scenario writer sees only the target's committed tree, read-only; instruction-surface diffs are owner decisions (5.4); every scenario passes lint and the negative control |
| a `security` job ships unattended and weakens security (Q4) | `security` was always reviewed by a person at level 4 | the full gate set of every type plus the 5.4 diff rules (which stop any type), the secret scan before a `github` push, post-ship regression set and rollback; `infra` still stops |
| shipping to GitHub publishes a secret or triggers CI with repository secrets (Q2) | nothing was pushed automatically | secret scan of every diff before the push (a finding is a DECISION); `.github/workflows/` diffs are owner decisions; push credentials live only in the factory process, masked in every phase |
| holdouts erode: the producer learns them through repeated failures | no holdouts existed | redacted hints only, exposure budget, rotation, canary and literal scans (3.5, 3.6) |
| runaway cost or an endless loop | a person started each job | per-goal hard limits checked every tick; unmeasurable budgets refused before the start; a budget stop pauses and escalates (6.2) |
| errors compound: job 2 builds on a defect job 1 shipped | jobs were reviewed one by one | serial jobs per project; the regression set re-runs every shipped holdout after each ship; rollback (5.3) |
| a rollback fails and the target is left broken | nothing shipped automatically | tree-equality check; a failed rollback halts all shipping and escalates; nothing is forced (5.3) |
| the factory goes silent | a person was watching | a notifier failure halts the factory; heartbeat on the view; doctor WARN (6.3, 6.4) |
| shipped content steers later phases (prompt injection through the repo) | a person read the repo | instruction-surface and import-hook diffs are owner decisions (5.4); the target is read-only to phases (2.4) |
| the factory changes its own rules, goals or ledger | there was no factory state to change | machinery list grows (`var/factory`, `var/holdout`); goals copied with an immutable hash; append-only ledger (2.3, 6.5) |
| a notification leaks code or secrets | there were no notifications | redacted one-line reasons, URL rules, no content fields (6.3) |
| work in a project outside the goal | a person chose the project | jobs filed only under the goal's project root; F-13 path rules (4.3) |

## 11. Not in level 5

- Several jobs of one project in parallel (the per-project lock stays; parallelism is across
  projects, later).
- Several hosts, a hosted service, or a board reachable from the network (loopback stays).
- A model deciding "done", "ship" or "roll back": holdouts, the DoD check, the verifier and the
  ship guard stay code. Reviewer phases (the DoD review included) write verdict files as they do
  at level 4, and a SHIP from them never replaces a mechanical check.
- Deploying through a built-in target (pushing to GitHub and merging a pull request IS built in
  since the owner's decision Q2: the `github` target; deploys stay with the `command` target and
  an owner-written `rollback_cmd`).
- Training or tuning models on factory transcripts.
