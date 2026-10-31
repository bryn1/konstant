# konstant level 5: the dark factory

Status: **plan**. Nothing on this page exists in 0.1.0. It is the design that the next releases
build in the waves listed in section 8; DESIGN.md, CONCEPTS.md and CLI.md change wave by wave as
each part lands, and this page stays the roadmap until level 5 is reached.

## 0. Levels

| level | who writes what | what konstant does | where the owner looks |
|---|---|---|---|
| **4** (0.1.0, shipped) | the owner writes each job and its Definition of Done (DoD) | gate -> phases -> DoD loop -> independent verify, unattended | outcomes: `verified`, or a stop with the reason written down |
| **5** (this plan) | the owner writes **goals and limits** | goal -> jobs with generated DoD -> held-out acceptance scenarios -> phases -> verify -> **ship** -> post-ship checks -> rollback on failure, inside budgets | only BLOCKED, owner decisions and budget stops; no human writes or reads code |

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
bubblewrap jail (`jail.py` `wrap`/`session`), **whatever the harness**. Today only dsh confines
itself (`harnesses/dsh.py` `Dsh.confine`). Level 5 generalises `Adapter.confine`
(`harnesses/base.py`) so claude, codex, gemini and `command` phases run inside the same jail when
factory mode is on. Each harness keeps its own sandbox nested inside, as dsh's does today.

- Without a working jail (`jail.available()` false, `[gate] jail = false`, macOS), `factory run`,
  `intake` and a `task run` of a job with sealed holdouts exit 2 with `holdouts need a confined
  phase`. Nothing falls back to "procedural".
- Inside the jail a phase can read exactly one role token, the token of its own identity
  (2.2), through `expose=`, the mechanism dsh phases already use for `worker.token`.
- A harness needs its own credential file to reach its model. For a jailed claude or codex phase
  the jail exposes only that file, as `machinery.SELF_HOME` already does for their sandboxes.
- Open point, verified in wave L5-2: Claude Code's own Bash sandbox nested inside konstant's jail.
  If it does not nest, a claude phase in factory mode runs with Claude Code's sandbox off and
  konstant's jail as the boundary. `doctor` says which.

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
sealed its holdouts, and the existing closer rule (`verdict`, `review`) stays. Under one OS user this separation holds because
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

`machinery.py` gains `var/holdout` and `var/factory` in `DIRS` (no phase writes them) and a new
tuple `SEALED = ("var/holdout",)` (no phase reads it). `jail.hidden()` masks `SEALED` next to
`var/secrets/`. Every adapter renders `SEALED` as a read denial (3.3). The existing test that
checks every machinery entry against every adapter
(`tests/review/test_review2_harness.py::test_G03_every_machinery_path_has_a_rule_in_every_adapter_and_the_jail`)
is extended to `SEALED`.

### 2.4 Job clones and the target

In factory mode a job's phases never touch the target repository. When a job is claimed,
konstant creates `projects/<slug>@<job>/` from the target's current tip. konstant writes the tree
itself from `ls-tree`/`cat-file` (the raw-blob way `gate/rules/common.py` already reads trees), so
no checkout, filter or hook runs. The run record's `project` is the clone, and the existing
one-run-per-project lock (`cli/task_run.py` `project_lock`) applies to it. The board records the
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
src/konstant/board/migrations/0002_factory.sql
```

`0002_factory.sql` (`board/migrate.py` drives it from `schema_meta.version`):

| table | columns (essential) | rules |
|---|---|---|
| `goals` | `id, slug, project_id, spec_json, spec_sha256, status (active/paused/done/stopped), created_at` | `spec_sha256` immutable (trigger, like `jobs_acceptance_immutable`) |
| `holdouts` | `id, job_id, hid, kind (proof/regression), sha256, author_label, sealed_at, state (sealed/burned/retired)` | no delete; `sha256` immutable; no content column |
| `ships` | `id, job_id, goal_id, target, commit_sha, pre_ref, rollback_sha, state (shipped/rolled_back/rollback_failed), post_json, created_at, updated_at` | append-only state changes |
| `budget_ledger` | `id, goal_id, job_id, run_id, kind (wall_s/task_runs/phases/tokens/cost/rollbacks), amount, at` | append-only (trigger, like `trail_no_update`) |
| `escalations` | `id, goal_id, job_id, kind, reason, delivered_at, acked_by, created_at` | append-only except `delivered_at`/`acked_by` |

`jobs` gains `goal_id`, `holdout_required`, `workdir` (the job clone) and `budget_json`.
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
KIND: proof                       # proof: must FAIL before the work; regression: must PASS before and after
RUN: python3 -c "from greeter import greet; print(greet('Ada'))"
EXPECT_EXIT: 0
EXPECT_OUT: hello Ada             # exact stripped stdout; or EXPECT_RE: ^hello Ada$ (fullmatch)
HINT: names other than the default are used verbatim
CANARY: khc-6c1d0f0e9b2a47d8a3f5
```

- `RUN` is a command, as a DoD `VERIFY_CMD:` is. It may not call a test runner (`pytest`,
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
   - every key is present, and `RUN` parses with the same safe-character rules as probes;
   - the expectation is not trivial;
   - **held out**: no expectation literal of 4 or more characters and no quoted `RUN` argument
     appears in the job's brief or acceptance (`NOT HELD OUT: H1 ...`);
   - the job has at least `[holdout] min_per_job` scenarios (default 2), and at least one of
     them is `proof`.
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
- **Independence beyond identity**: `[holdout] writer_harness` / `writer_model` may name another
  harness or model than the producer's (`[harness.types]` already lets types differ). `doctor`
  WARNs when the scenario writer and the producer resolve to the same model (owner question Q1).

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
  (`verifier.separation`). `doctor` reports which mode applies (owner question Q3).
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

### 4.1 Goal file

The owner writes a goal and its limits, nothing else:

```toml
# goals/greeter.toml
[goal]
id = "greeter"
project = "greeter"                 # an existing konstant project (its path rules: F-13)
text = """
A small greeting library: greet(name) and a CLI `greet NAME`, documented in README.
"""

[limits]                            # required: wall_clock and max_task_runs (owner question Q5)
wall_clock = "4h"
max_task_runs = 20
max_jobs = 8
max_rounds_per_job = 3              # board max_rounds applies too; the smaller wins
max_rollbacks = 2
max_tokens = 0                      # 0 = not limited; > 0 needs a harness that reports usage (6.2)
max_cost_usd = 0

[ship]
target = "branch"                   # branch | apply | command (5.1)
branch = "main"
post_probes = ["PROBE: test -f projects/greeter/README.md => ^ok$"]

[holdout]
author = "agent"                    # agent | owner (owner: jobs wait for `holdout add`)
min_per_job = 2
```

`konstant goal add FILE` (owner role) validates the file (`factory/goal.py`), copies it into
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
     (owner question Q4);
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
| a planner and producer collude (same model) | distinct labels enforced by the board; distinct harness/model configurable with a doctor WARN (Q1); holdouts are the independent check |
| a brief changed after the review | `JUDGED` pin over the backlog and briefs; the board stores the acceptance immutably at filing |
| a producer of job 1 plants instructions in the repo for later planners or scenario writers (prompt injection through shipped content) | ship escalates any diff to project instruction surfaces (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `.agents/`, `.dsh/`, `.gemini/` inside the project) as an owner decision (5.4); scenario lint and the negative control bound how weak a scenario can be |
| intake files jobs in another project or outside the goal | filing only under the goal's project root; projects keep their F-13 path rules |
| intake floods the board | `max_jobs`, `max_task_runs`; intake runs once per goal unless the owner re-opens it |

### 4.4 Acceptance (pillar B)

| # | command | expected |
|---|---|---|
| B1 | `bin/konstant --as owner goal add examples/greeter/goal.toml` | `goal greeter added (sha256 ...)`; a copy at `var/factory/goals/greeter.toml` |
| B2 | the same file without `[limits] wall_clock` | exit 1 `goal: limits.wall_clock is required` |
| B3 | `bin/konstant intake greeter; RC=$?` (fake harness) | `RC=0`; `bin/konstant job list --project greeter --json` lists the backlog jobs in `waiting_approval` and then `queued`; `bin/konstant job lint <each brief>` exits 0 |
| B4 | `FAKE_HARNESS_MODE=weak-dod bin/konstant intake greeter; RC=$?` | `RC=3`, `UNMET: job B2 DoD has no PROBE`; no job filed |
| B5 | `bin/konstant job show <job> --json --trail` | trail actors in order: `planner` (add), `dod-reviewer` (dod-review SHIP), `factory` (approve), `scenario` (holdout x2); pairwise distinct |
| B6 | a test posting `approve` with the requester's own label | HTTP 403 `the requester cannot approve its own DoD` |
| B7 | a test where `dod-reviewer` tries `claim` | HTTP 403 `the DoD reviewer of a job cannot claim it` |
| B8 | `bin/konstant task classify "intake the backlog for the goal"` | the type is not `intake` |
| B9 | `python -m pytest -q tests/factory/test_scenario_isolation.py` | exit 0: the scenario phase's prompt names no job clone, OUT or run path; its run dir lies under `var/holdout/` |
| B10 | `bin/konstant job show <job> --json` | `"goal_id"` set, `"budget"` with the job's share of the limits |

## 5. Pillar C: auto-ship

### 5.1 Targets

| target | ship | post-ship | rollback |
|---|---|---|---|
| `branch` (default) | `update-ref refs/heads/<branch> <commit> <pre>` in the target repo (compare-and-swap; fast-forward only) | `post_probes`, the project's own tests and **every holdout of every job shipped so far** on the new tip | `commit-tree <pre>^{tree} -p <tip>` -> a new "roll back ship N" commit, then `update-ref` (CAS) |
| `apply` | materialise `<commit>` into `[ship] apply_dir`, keeping the previous tree as `apply_dir.prev` | `post_probes` against `apply_dir` | swap `apply_dir.prev` back |
| `command` | the owner's `ship_cmd` template (e.g. a `gh pr create` or a deploy script), run by the factory process with `{commit}`, `{branch}`, `{job}` | `post_probes` | the owner's `rollback_cmd`; a target without one may not auto-ship |

The branch target never rewrites history. A rollback adds a commit whose tree equals the
pre-ship tree, so the shipped commit stays an ancestor and the record stays readable. A target
branch that is checked out in a non-bare worktree is refused (`update-ref` would leave that
worktree stale); `apply` is the target for a working directory. Network push is never done by
the built-in targets (owner question Q2): a `command` target that pushes runs outside every
phase, with credentials no phase can read (`machinery.CREDENTIALS` stay masked in phases).

### 5.2 The ship guard (board-side and code-side)

`konstant ship JOB` (`factory/ship.py`, identity `factory`) ships only when **all** hold. The
board checks the same conditions again on `POST /api/jobs/{ref}/ships`:

1. the job is `verified`, and its latest `verifications` row is PASS;
2. that row's `holdout_json` lists at least `min_per_job` holdouts, all passed, with the
   commitment digest equal to `holdouts.sha256` for each, and states **no LEAK**: **never ship
   without a matched holdout**;
3. the commit those holdouts ran on equals the evidence `COMMIT=` and the commit about to be
   shipped;
4. the target tip still equals the job clone's base (`pre`). With jobs serial per project only
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

- a job type in `[ship] decision_types` (default `infra`, `security`; Q4);
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

Limits come from the goal (`[limits]`) and are recorded per job (`budget_json`). Spending is
written to `budget_ledger` by code:

| kind | measured from | always available |
|---|---|---|
| `wall_s` | phase manifests (`phases/*.json` `duration`) and the loop's own clock | yes |
| `task_runs`, `phases` | the runner's records | yes |
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
| D1 | goal with `max_task_runs = 1`, `FAKE_HARNESS_MODE=tester-fails-3x`, `bin/konstant factory run greeter --until-idle; RC=$?` | `RC=4`; `$WS/var/factory/notify.log` has one line starting `BUDGET_STOP greeter`; `bin/konstant goal show greeter --json` `"status": "paused"` |
| D2 | goal with `max_cost_usd = 5` on the `command` harness | `RC=2`, `budget max_cost_usd cannot be measured on harness command` |
| D3 | an honest goal run to completion | `RC=0`; `notify.log` has 0 lines; `events.jsonl` has `SHIPPED` rows |
| D4 | `bin/konstant notify test --kind webhook` against a local test server | the server receives JSON with `event` and `reason`, and without `brief`, `acceptance` or `evidence` keys |
| D5 | a webhook that refuses every request, during a run | the factory exits 4 `notifier failed: factory halted`; the event is in `var/factory/spool/` |
| D6 | `curl -s -H "Authorization: Bearer $VIEWER" http://127.0.0.1:$PORT/api/factory/goals/greeter` | JSON with `budget`, `jobs`, `ships`, `escalations`; no `RUN`/`EXPECT`/`khc-` text |
| D7 | `bin/konstant factory start; bin/konstant factory start; RC=$?` | the second `RC=2`, `a factory already runs (pid ...)`; `bin/konstant factory stop` -> `factory status` `stopped` |
| D8 | `chmod 000 $WS/var/secrets/owner.token; bin/konstant factory run greeter --until-idle; RC=$?` | `RC=0` (no human role needed) |
| D9 | `python -m pytest -q tests/factory` | exit 0; every refusal above has a `_red` and a `_green` test |

## 7. Proof of level 5

One command, a goal file and a sample project, no human input, run offline with the fake harness:

```sh
bash tests/e2e/factory.sh        # builds the tarball, installs it fresh, runs the five legs below
```

The sample lives in the release: `examples/greeter/` (a tiny Python project with a README and one
test) and `examples/greeter/goal.toml`. **No scenario ships in the release**: everything in the
workspace is readable by phases. The legs use the scenario writer (`author = "agent"`, the fake
harness's scenario mode), and one extra check uses `author = "owner"` with two scenarios the e2e
script writes into its own temp dir outside the workspace and seals with `holdout add`. stdin
is `/dev/null` and `owner.token` is unreadable for the factory's whole run.

| leg | setup | expected |
|---|---|---|
| P1 honest | default fake harness | `factory run greeter --until-idle` exit 0; every backlog job `verified`; `ship list --json` all `shipped`; `git -C projects/greeter log main` has one fast-forward per job; `notify.log` empty |
| P2 cheating producer | `FAKE_HARNESS_MODE=overfit` (the visible DoD passes, held-out inputs fail) | verify FAIL `holdout H1 failed`, max rounds -> BLOCKED; **no ship**: the target tip unchanged; `notify.log` one `BLOCKED` line; exit 4 |
| P3 reader | `FAKE_HARNESS_MODE=peek` | every read of the store denied (phase log); no canary in the diff; then the same leg with `[gate] jail = false`: `factory run` exit 2 before any phase |
| P4 post-ship failure | `FAKE_HARNESS_MODE=ship-break` | ship, post-ship probe FAIL, automatic rollback: the target tree equals the pre-ship tree, the shipped commit still an ancestor, a follow-up job filed; after `max_rollbacks` BLOCKED + one notification; exit 4 |
| P5 budget | `max_task_runs = 2` with `tester-fails-3x` | `BUDGET_STOP` notification, goal paused, exit 4 |

The e2e prints `E2E-FACTORY: PASS` only when every leg met its row, and each leg's checks read
artifacts (the git refs, `ship list --json`, `job show --json`, the notifier file), never the
loop's own summary.

**Optional live run** (`tests/e2e/factory_live.sh`, not part of CI): the same P1 leg with a real
model through dsh and a local OpenAI-compatible endpoint (the address only in the environment of
that run), plus P2 with a prompt that asks the producer to special-case the visible example. It
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
| **L5-1** sealed holdouts (before L5-2 only dsh phases are confined, so the adversarial modes run through the real dsh adapter with `tests/fixtures/stub_dsh.py`, as the second review's fixes did) | scenario format, `holdout add/list/check/show`, `holdout/store.py` + `lint.py` + `leak.py`, `verify/holdout.py` (pinned materialisation, jailed no-network runs, redacted findings), settle extension, `0002` tables `holdouts` + `verifications.holdout_json`, `machinery.SEALED` in jail + all adapters, DECLINED cannot excuse holdouts, the claim guard, `jobs.holdout_required`, fake modes `overfit`, `peek`, `leak` | `machinery.py`, `jail.py` `hidden`, `verify/verifier.py` `settle`/`verify_job`, `verify/rerun.py`, `agents/settings.py` `render`, `harnesses/codex.py` `filesystem`, `harnesses/gemini.py`, `gate/rules/done.py`, `board/migrate.py` | v0.1.0 | A1-A3, A5-A13 (through the dsh adapter) |
| **L5-2** confinement + identities | generalised `Adapter.confine` for every harness in factory mode, one exposed identity token per phase, labelled worker tokens, board label guards, job clones + target read-only, `jobs.workdir` and the `{workdir}` probe substitution (`verify/probe.py`, `verifier.project_dir`), `Adapter.relocatable_home`, doctor `factory` rows, live smoke of a jailed claude phase (records whether Claude's sandbox nests) | `harnesses/base.py`, `claude.py`, `codex.py`, `gemini.py`, `command.py`, `board/auth.py`, `board/api/lifecycle.py`, `board/transitions.py`, `cli/task_run.py`, `cli/doctor.py` | L5-1 | A4 on every adapter, B6, B7, C9 |
| **L5-3** intake + scenario writer | goal files (`goal add/list/show/pause/resume/cancel`), type `intake` + agent `planner`, `DOD-verdict.md`, deterministic filing, approval rule, role agent `scenario-writer`, `holdout/author.py` with the run dir in the store, fake planner / reviewer / scenario modes incl. `weak-dod` | `catalog/types.yaml`, `catalog.py` `ROLE_AGENTS`, `board/dod.py` `lint`, `gate/runner.py`, `gate/rules/authorship.py`, `gate/rules/judged.py`, `agents/generate.py` | L5-2 | B1-B5, B8-B10 |
| **L5-R1** independent review 1 | review only, by someone who built none of L5-1..3: try to reach `verified` past holdouts, read the store from every harness, leak through feedback, transcripts, the board or run records, forge identities, weaken a generated DoD; one reproduction per finding | the adversarial fake harness, as the first two reviews did | L5-3 | report with severity per finding |
| **L5-F1** fixes 1 | one red-then-green test per finding under `tests/review/` (`test_H<nn>_...`); zero open P0/P1 | — | L5-R1 | all A and B rows green again |
| **L5-4** ship + rollback | `ship`, `ship list`, targets `branch`/`apply`/`command`, the guard on both sides, plumbing-only ref moves, post-ship checks with the regression set, rollback + tree check, the follow-up job after a rollback, halt on a failed rollback, decision rules (5.4), table `ships`, fake modes `ship-break`, `self-ship` | `gate/rules/common.py` git plumbing, `verify/probe.py` `run_line`, `verify/holdout.py`, `board/api/` | L5-F1 | C1-C10 |
| **L5-5** factory loop + budgets + notifier + view | `factory run/start/stop/status/ack/resume-shipping`, `budget_ledger`, `Adapter.usage`, unmeasurable-budget refusal, `notify` (stdout/file/webhook), `escalations`, `board/api/factory.py`, the Factory tab | `gate/loop.py`, `cli/task_run.py`, `cli/board.py` (pid handling), `board/redact.py`, `board/static/` | L5-4 | D1-D9 |
| **L5-6** proof of level 5 | `examples/greeter/`, `tests/e2e/factory.sh` (P1-P5), CI job, QUICKSTART "level 5" section, the optional live run recorded | `tests/e2e/fresh_install.sh`, `tests/fixtures/fake_harness.py` | L5-5 | `E2E-FACTORY: PASS`; full `pytest`; release build CLEAN |
| **L5-R2** independent review 2 | review of the whole factory (ship, rollback, budgets, loop, notifier, view) plus a regression run of F-01..F-35, G-01..G-07 and the L5-R1 findings, on a tarball installed the documented way | — | L5-6 | report |
| **L5-F2** fixes 2 + release | red-then-green tests per finding, zero open P0/P1, CHANGELOG, a release build; tagging and publication are the owner's step | — | L5-R2 | full `pytest`, `E2E-FACTORY: PASS`, `RESULT: CLEAN` |

**Level 5 is reached when L5-F2 is done**, not before: two independent reviews, the second one
after everything (ship and rollback included) exists.

## 9. Open questions for the owner

Each has a default the build proceeds on until the owner answers. None of them is hard to change
later.

1. **Who writes holdouts by default?** Default: the `scenario-writer` agent per job, on another
   harness or model than the producer when one is configured (`doctor` WARNs when they are the
   same), and the owner may add scenarios to any job before it is claimed. Alternative: owner-only
   holdouts (`author = "owner"`), which is stronger and also means the owner is contacted for every
   job.
2. **What does the default ship target touch?** Default: a local branch only (fast-forward of
   the project's branch, never a network push); pushing, pull requests and deploys are opt-in per
   goal through the `command` target with an explicit `rollback_cmd`.
3. **Is a second OS user required for unattended runs?** Default: no. The jail is required (fail
   closed), and the second-user mode (store and verifier under another user) is recommended,
   documented and reported by `doctor`. Requiring it makes setup harder on every install.
4. **Which job types may ship without the owner?** Default: `code`, `frontend`, `test`, `docs`;
   `infra` and `security` jobs always stop as an owner decision before ship.
5. **Must every goal name its budgets?** Default: yes for `wall_clock` and `max_task_runs`
   (always measurable); `max_tokens` and `max_cost_usd` stay optional because not every harness
   reports usage, and a set one is refused on a harness that cannot measure it.

## 10. Risks: what a dark factory can do wrong that level 4 could not

| risk | why level 4 was safe from it | mechanical guard at level 5 |
|---|---|---|
| broken code reaches the target with nobody looking | a person decided what to merge | ship only on `verified` with every holdout passed on the exact commit (5.2); post-ship checks, regression set, automatic rollback (5.3) |
| a weak, self-generated DoD makes "verified" meaningless | a person wrote the DoD | DoD lint without warnings, at least one PROBE per job, review by a different identity, holdouts from a third identity that must fail on the base (3.2, 4.2) |
| one model writes the DoD, the holdouts and the code, and they agree on the same mistake | a person wrote the DoD | distinct identities enforced by the board; distinct harness/model configurable with a doctor WARN (Q1); holdouts black-box only |
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
- Pushing to a remote, opening pull requests or deploying through a built-in target: the
  `command` target with an owner-written `rollback_cmd` covers those.
- Training or tuning models on factory transcripts.
