# Changelog

All notable changes to konstant. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

Level 5, the dark factory (docs/LEVEL5.md; waves L5-1 to L5-7, pending the second independent
review and its fixes before a release).

### Added
- **Sealed holdouts** (`holdout add/list/check/show`, the scenario writer): held-out acceptance
  scenarios a producing phase can never read, run by the verifier on the exact commit.
- **Factory mode confinement and identities**: every phase of a holdout job jailed on every
  harness, one identity token per phase, job clones with the target read-only; confinement
  profiles `closed` / `open` around a fixed integrity core.
- **Intake from the orchestrator chat** (`goal add --from-chat`, `chat turn`): a request becomes a
  goal proposal, the owner's "yes" files it; goal files, planner, DoD review, deterministic filing.
- **Built-in memory** (`memory`, `konstant mcp memory`): a Markdown vault with recall, one shared
  pool for producers and a sealed pool for the judges.
- **Triage** (size tiers, the intake card, the closed researcher, the licence gate).
- **Ship and rollback** (`ship`, targets github / branch / apply / command): post-ship checks,
  revert rollback, follow-up jobs, owner decisions for CI, instruction surfaces and secrets.
- **The factory loop** (`factory run/start/stop/status/resume/ack`), budgets (`max_attempts` the
  one required limit), the notifier (stdout, file, webhook, chat) and the board's Factory tab.
- **The proof of level 5**: `examples/greeter/` (a sample project and goal) and
  `tests/e2e/factory.sh` (legs P0-P6: chat intake, honest, cheating, reader, post-ship failure,
  budget, GitHub through a stand-in; offline, from a fresh install); the optional live run
  `tests/e2e/factory_live.sh`.
- CI: bubblewrap on the runner, the release build and scan, the one-line-install and factory e2e.
- **A scenario writer one local model can satisfy** (L5-7): rules and worked examples in its
  prompt, `holdout lint --draft` (the seal's own lint, run inside its phase) and `holdout new`
  (a skeleton), the seal's reasons per draft on a retry, `[holdout] author_attempts`
  (default 3). No lint rule changed; a skeleton placeholder is a new refusal.


### Changed (wave L5-L2: verdict identity, the review items, live acceptance round 2)
- **A verdict file is a `*verdict*.md` file directly in OUT**, created by the phase run konstant
  named it for (no longer any verdict-named file anywhere under OUT, credited by its stem): a
  verifier's private `OUT/verify-<stem>/` holds evidence under any name, pinned by its verdict;
  every write there by another phase run taints the run (the manifests prove it, jail or not).
  The live false positive (a closing architect's `verify-arch/a5-verdict-prejudge.md`) is gone,
  and two shadowing attacks that were MET inside the tester || reviewer group are refused.
- **The held-out lint reads the goal's other jobs** (title, brief, DoD), and the scenario writer's
  prompt and pre-check see them: a literal another job's DoD shows is not held out.
- **An empty producing phase** (exit 0, nothing changed in OUT or the project) is retried once in
  its cycle, like a crashed verifier.
- **The live acceptance passed**: the three-job greeter goal, from a plain chat request, on one
  local model: every job verified on its first attempt and shipped, `GOAL_DONE` in the chat,
  0 canary leaks, 4 h 45 min (docs/LEVEL5.md "L5-L2 as built").

### Changed (wave L5-L: the live acceptance of level 5)
- **`konstant doctor --live-preflight`**: before a live goal, ONE real jailed dsh phase runs
  through the real runner, adapter and jail, as the scoped tester of a throwaway factory job, on a
  scripted local endpoint (no model call), and its own shell reports: git works in the job clone,
  its token is readable and the others are not, the sealed store is masked, the
  `OUT/verify-<stem>/` layout holds, and the pin made inside matches the DoD check outside.
  `tests/e2e/factory_live.sh` runs it first and stops on a FAIL; on the L5-F2b code it reproduces
  that run's live finding (`missing config key GIT_CONFIG_KEY_0`, a stale pin).
- **The stub dsh is faithful to dsh's bash tool**: a model command gets the harness's environment
  minus every `KEY`/`PASSWORD`/`SECRET`/`TOKEN`-shaped and `DSH_*` name, plus dsh's own overrides
  and `DSH_*` facts, stdin `/dev/null` (measured live by the pre-flight); a model-loop mode drives
  the pre-flight in CI. The factory suites through the stub now fail on the L5-F2b base the way
  the live run did.
- **Fixed: the konstant-gate plugin's per-command markers never reached a real dsh's bash** (dsh
  takes `DSH_*` keys only): they are `DSH_KONSTANT_ROLE`, `DSH_KONSTANT_IN_TASK` and
  `DSH_KONSTANT_CHAT_SESSION`, and konstant reads both spellings. Before this, a delegated child
  in the owner's session was not marked worker and the chat's refusals (`intake`, `holdout
  author`, `--as owner`, the factory identities) did not apply to the session's own bash.
- **Fixed, from the two live runs of this wave** (each red-then-green, none run live after its fix):
  `--until-idle`/`--once` wait out a board that stops answering for `[factory] down_after_s` at
  most instead of halting on one timeout, and an internal error stops the steps the factory
  started (a ship is never cut); a verifying phase whose harness crashed before its verdict is
  run once more in its cycle; a close-out writes only DONE.md and CYCLES.md in OUT (the rest is
  read-only to it, its other files are moved to `OUT/.tmp/closeout/`), so it can no longer stale
  the verifiers' pins after every resume; a refused memory write fails the verification round
  it belongs to only; a held-out literal that the writing phase's own brief shows is public to
  its memory notes; a failing test in a verifier's `OUT/verify-<stem>/` is that verifier's to fix,
  not the producer's.

### Changed (wave L5-F2b: the second review's owner-seat findings K-05, K-08, K-09, K-11, K-13, K-14, K-16..K-18, and speed)
- **Every chat hears the factory**: one owner inbox that every `konstant dsh` session shows at its
  next turn (a new session shows what is still open); delivered when a turn showed it; a byte
  cursor, so nothing that lands mid-turn is skipped; `notify test` is a real event; doctor checks
  the route end to end; `[notify] mirror` (file or webhook) is a second channel (K-05, K-08, K-16).
- **Routing on the owner's words** (`factory/route.py`): work requests are proposed as goals by
  default, "just answer" keeps them inline; only documented yes-forms (yes, ja, go, ...) file a
  goal, never "ok" or "sure" (K-09).
- **Reboots**: `factory install-unit` writes a board unit and a factory unit that wants it; the
  factory restarts on a refusal with a growing delay and waits out a down board, telling
  "factory down" through the mirror; doctor reports stale units (K-13).
- **Rollback reverts only the ship commit's change** on the current tip; a conflicting revert is
  an owner decision (K-14). **Follow-up chains are capped** (`[factory] max_follow_ups`, 3) and
  every rollback is an escalation (K-17).
- **Holdouts**: the held-out lint reads the goal text (K-11); a seal cut off before its rename is
  recovered or discarded (K-18).
- **Speed**: scoped pins (each non-producing verifier owns `OUT/verify-<stem>/`; another
  verifier's evidence no longer stales its verdict; the jail keeps the dir its owner's) and
  `[gate] phase_timeout_s` (tester and reviewer 7200 s, others 3600 s).

### Security (wave L5-F2a: the second review's integrity findings K-01..K-04, K-06, K-07, K-10, K-12, K-15)
- **Pinned harness programs**: `agents sync` records each harness CLI and `[ship] gh` /
  `ship_cmd` / `rollback_cmd` with the sha256 of their program files; konstant's own unjailed runs
  refuse a changed or unpinned one, and the dsh composition check and doctor's version probe run
  jailed (K-01).
- **Goals cannot name where or how they ship**: only `post_probes` under `[ship]`; the proposal and
  the FILED line show the goal text verbatim and every non-default setting (K-02).
- **The ship commit**: every target ships konstant's squash of the verified tree onto the target's
  tip, never the job's history; an orphan or unrelated history is an owner decision (K-03, K-04).
- **Factory state jails every phase**, level 4 included (K-06); **no push credentials in a factory
  phase** in any profile, opt back in with `factory_host_credentials = true` (doctor FAIL) (K-10).
- **Chat**: producer text is quoted and labelled, never a konstant line; owner verbs from the chat
  are proposals the owner's next yes confirms (K-07); `factory stop`/`resume` are owner-only (K-12).
- **One decision list** for ship-time owner decisions, case-insensitive, all of `.github/`,
  test-runner and editor config, package scripts (K-15).
### Security
- Fixes from the first independent level-5 review (H-01..H-09; docs/LEVEL5.md "L5-F1 as built").

## [0.1.0] - 2026-10-31

First public release.

### Added
- **Board**: local job board (FastAPI + SQLite, loopback only) with five token roles (owner,
  orchestrator, worker, verifier, viewer), a one-table job state machine, projects with a job tree
  of depth 2, an evidence contract on every close (`VERIFY_CMD:` + `VERIFY_EXIT=0`, vacuity
  refusal, optional negative control), secret redaction, a read-only web view, `board backup`.
- **Task gate**: deterministic classifier over nine task types (code, frontend, infra, test,
  security, review, research, docs, design) plus `small`; one agent profile per type; fixed phases
  with verdict files; `task gate`, `task run` (phase runner + bounded DoD loop), `task check`
  (13 mechanical Definition-of-Done rules, exit 0 MET / 3 UNMET / 4 BLOCKED), `task judge`,
  `task close`.
- **Verifier**: `konstant verify` re-checks closed work with allowlisted read-only probes and a
  re-run of the recorded verify command; it passes a job only on a matched `PROBE:` from the job's
  DoD, and only the verifier (or owner) can mark a job `verified`, never the identity that closed it.
- **Catalog**: 10 agent profiles, 26 skills, 9 workflows and shared doctrine, generated by
  `konstant agents sync [--check]` into the surfaces of each configured harness: `.claude/agents`,
  `.claude/skills`, `.claude/settings.json` (workspace-scoped permissions), `CLAUDE.md`,
  `AGENTS.md` (with "Operating konstant (any agent, any model)": `--json`, `--help`, exit codes,
  the command table and what an agent never runs), `.agents/skills/`, `.dsh/`, `.gemini/`.
- **Any harness, any model** (docs/HARNESSES.md): adapters for Claude Code, Codex (`codex exec`),
  Gemini CLI, DeepSeek Harness (`dsh`) and any CLI (`command`), chosen by `[harness] name`, with
  `[harness] model`, a local OpenAI-compatible `[harness.endpoint]` (codex, dsh) and per-type
  overrides `[harness.types.<type>]`. Each adapter maps the workspace-scoped reach onto the
  harness's own permission system (Claude settings, codex permission profile, Gemini CLI policy
  file, dsh sandbox patch) and relocates or skips user-level configuration where the harness
  allows it; `doctor` reports each harness and what it does and does not enforce.
- **dsh sessions with the same loop** (docs/DSH.md): the `konstant-gate` dsh plugin (TypeScript
  source + vendored build in `src/konstant/harnesses/dsh_gate/`) gates every typed message of a
  dsh web/tui/headless session, runs the DoD loop at the end of the turn and closes + verifies a
  bound job, never gating a delegated child, whose bash acts as `worker`. `bin/konstant dsh APP`
  starts dsh with konstant's layers and refuses a session whose composition it cannot read or that
  loads a foreign layer.
- **Install**: the one-liner `curl -fsSL
  https://github.com/bryn1/konstant/releases/latest/download/get.sh | bash` (POSIX sh; checks the
  prerequisites, verifies the tarball's sha256 before unpacking, refuses a non-empty or unreadable
  folder and any tar member that is not a file or a folder, leaves nothing behind on a failure);
  `install.sh` (idempotent; venv, falls back to virtualenv without ensurepip; `--wheels` offline;
  `--from` upgrade; `--harness`), the `bin/konstant` wrapper, `konstant doctor`.
- **Release tooling**: `python -m konstant.release build|scan|clidoc`, a public-safety scan of
  every shipped file, fresh-install and one-line-install end-to-end tests.

### Security
Two independent security reviews ran before this release (docs/CONCEPTS.md "Security reviews").
Every finding has a test under `tests/review/`; none of P0/P1 severity is open. In summary:
- A DONE.md `DECLINED` row needs an owner note on a board job; it never waives what the verifying
  phases or the tests say. Nobody reviews a job they filed, claimed or closed; harness phases act
  as `worker`.
- `task check` judges only run records under `var/runs/` and takes its settings from the
  workspace, never from the record; agent-written tests, verifier re-runs and every dsh phase run
  in a bubblewrap jail when available; nothing a phase starts outlives it (Linux).
- No probe shape and no git read of konstant's own runs a repo-configured command; probes never
  read `var/`; project paths cannot widen the probe roots.
- One list of konstant's machinery (`src/konstant/machinery.py`: the release's code, every
  generated harness surface, `var/harness/`, `var/secrets/`, the board DB, `.git/`) that no phase
  may write, enforced by the Claude settings, the codex profile, the Gemini policy and the jail;
  one list of credential homes the jail masks and the harness sandboxes deny. Each dsh phase gets
  a fresh dsh home of its own.
- Private file modes, a 1 MiB request cap, broader secret redaction, a loopback-only board unless
  `allow_remote = true`, a pid-checked `board stop`, an offline install that works from a
  `pip download` wheel dir. See docs/CONCEPTS.md "Security model and limits" for what remains.
