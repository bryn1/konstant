# konstant with DeepSeek Harness (dsh)

DeepSeek Harness (`dsh`, MIT, npm `@deepseek-ai/dsh`) is an agent harness with a web UI, a
terminal UI and a headless mode that speaks to any OpenAI-compatible server, including a local
model. konstant uses it two ways, with the same rules:

| you want | command | who drives the phases |
|---|---|---|
| konstant to run the whole task unattended | `bin/konstant task run --harness dsh "<task>" [--job N]` | konstant: one headless dsh run per phase, each inside konstant's jail |
| to drive the task yourself in dsh (web UI, tui, headless) | `bin/konstant dsh web` (or `tui`, `headless -`) | your dsh session: the `konstant-gate` plugin gates the task, runs the DoD loop and hands the job to the verifier |

Both end the same way: the mechanical DoD check (`konstant task check`) decides MET, the job is
closed with that check as its evidence, and `konstant verify` (a different role) moves it to
`verified`. A model never decides that its own work is done.

## Set up

```toml
# konstant.toml
[harness]
name = "dsh"
model = "my-model"                  # the name your server serves (GET /v1/models)

[harness.endpoint]
base_url = "http://127.0.0.1:8000/v1"   # vLLM, llama.cpp llama-server, Ollama ...
api_key_env = ""                         # the variable holding its key; "" = none needed
```

```sh
bin/konstant agents sync     # writes .dsh/ (see below) and AGENTS.md, .agents/skills/
bin/konstant doctor          # dsh found, its layers, its reach, the jail
bin/konstant board start
```

Use a stock `dsh` (`npm install -g @deepseek-ai/dsh`, or a source checkout's
`apps/cli/lib/bin.js`). A launcher script that exports its own `DSH_HOME` loads another profile
into every run; `doctor` names such a layer (`dsh layers` WARN) and `bin/konstant dsh` refuses to
start a session that would load one (exit 1). Install konstant outside `/tmp`:
dsh's sandbox gives every command an empty private `/tmp` (`doctor` WARNs).

`agents sync` writes, for dsh:

| file | what |
|---|---|
| `.dsh/konstant.patch.yml` | the reach of a phase: sandbox `workspace-write`, approval `never`, the workspace `AGENTS.md` and `.agents/skills/` only, your endpoint as provider `konstant` |
| `.dsh/konstant-session.patch.yml` | your own session's layer: the `konstant-gate` plugin with this workspace's settings (from `[gate]` and `[board.policy]`) |
| `.dsh/konstant-gate.mjs` | the plugin (a copy of the vendored build, see "The plugin") |
| `.dsh/agents/<agent>.md` | the composed agent profiles: dsh has no named subagent profiles, so a phase is a `subagent` whose prompt starts with that file |

They are generated: edit `catalog/` or `konstant.toml`, then sync again; `agents sync --check`
names drift.

## Your own dsh session: `bin/konstant dsh`

```sh
bin/konstant dsh web                         # the web UI (dsh's own flags follow: --port 3090 ...)
bin/konstant dsh --project demo tui          # the terminal UI, in project demo's directory
printf '%s' "[job:3] [type:docs] write USAGE.md" | bin/konstant dsh --project demo headless -
bin/konstant dsh --dry-run web               # print the argv, directory and environment only
```

It runs `dsh --profile APP --patch .dsh/konstant.patch.yml --patch
.dsh/konstant-session.patch.yml ...` with `DSH_HOME` in `var/harness/dsh/session/` (your own dsh
profiles, credentials, MCP servers and memory do not load), the model in `KONSTANT_MODEL`, in the
project's directory (`--project`), else the current directory when it is inside the workspace,
else the workspace. dsh's `workspace-write` sandbox lets the session write only below that
directory, so start it in the project you work on. The session is not jailed, so before it starts
dsh it refuses (exit 1, naming what it found) when:

- a generated dsh file differs from the catalog (`.dsh/konstant-gate.mjs`, the two patches,
  `.dsh/agents/`, `AGENTS.md`, `.agents/skills/`): run `bin/konstant agents sync`, and find out
  what changed it;
- packages are installed in the session's dsh home (`profiles/*/node_modules`: they would load
  before dsh's own bundles);
- the composed session (`dsh --dump-config`, no model call) holds any layer besides dsh's shipped
  bundles (as a fresh, empty home composes them) and konstant's two patches: an id-patch or an
  insert-only layer in the session home or anywhere else, a bundle added to a profile, a launcher
  that forces its own `DSH_HOME`;
- the composition cannot be read (dsh failed, or printed no layer: a dsh running on Node.js 20
  exits 0 with no output; dsh needs Node.js >= 22).

No phase can write the session home: it is under `var/harness/`, which every adapter and
konstant's jail keep read-only for phases, and each dsh phase gets a fresh dsh home of its own.
`--dry-run` runs no dsh at all.

The session is the **orchestrator**. For each message you send:

1. **Gate.** A typed task (`konstant task classify` says which; `[type:docs]` forces one) is
   replaced, before the model sees it, by the gate block + your text: the phases with their agent
   and verdict file, the OUT directory, the judge and check commands, the DONE.md shape and, with
   a job, the job's DoD rows. The run record goes to `var/runs/`. A small message (a question,
   "status") passes unchanged. Empty and `/`-command messages are never gated.
2. **Phases.** The model starts each phase as a dsh `subagent` whose prompt is
   `.dsh/agents/<agent>.md` + the phase brief. A delegated child is never gated and never gets a
   loop, and its shell commands run with `KONSTANT_ROLE=worker KONSTANT_IN_TASK=1`, so the
   konstant CLI refuses it every token but worker and viewer.
3. **DoD loop.** When the turn ends, the plugin runs `konstant task check --offline <run>`:
   - MET (0): see 4;
   - UNMET (3): a nudge with the reasons is steered into the same turn, up to `[gate]
     max_resumes` (3); the loop stops early when the first reason repeats unchanged;
   - BLOCKED (4): reported, never resumed (DONE.md honestly lists what could not be verified);
   - anything else: CHECK-ERROR, never MET, never resumed.
4. **Verifier hand-off.** MET with a job: `konstant task close <run>` closes the job (evidence =
   the offline check, `VERIFY_EXIT=0`, DONE.md) and runs `konstant verify`. PASS: the job is
   `verified` and the session is told so. FAIL: the verifier's reasons are steered back into the
   turn (its own budget, `[board.policy] max_rounds`; the UNMET budget starts again). BLOCKED or
   an error: reported. MET without a job: reported as MET.

Every decision is a line in `var/logs/konstant-gate.log`; every outcome is also a notice in
the session. A failing
gate never blocks you: your text goes through UNGATED and a notice says so.

**Binding a job.** Put `[job:N]` (or its display id `[job:1.2]`) in the message, or let the
session bind one: the job a typed message was bound to stays bound to the session
(`var/sessions.json`) and is claimed; with `[gate] file_job = true` a typed message that names no
job files one under the session's project (the message is the brief, so it needs a `DoD:`
section with at least one `PROBE:` line the verifier can run) and the plugin reports UNBOUND if
a MET run has no job. Example brief:

```text
[type:docs] Write projects/demo/USAGE.md: what the project is for and how to add a file.

DoD:
- projects/demo/USAGE.md exists, is committed, and starts with a "# Usage" heading
PROBE: grep -c "^# Usage" projects/demo/USAGE.md => ^[1-9]
```

## Unattended: `bin/konstant task run --harness dsh`

`--harness dsh` runs every phase of that run on the dsh adapter (the toml's per-type rows are
ignored for that run; `[harness] model` applies when the toml names dsh). konstant drives the
phases itself (architect, producer, verifiers, close-out), re-runs the phase that owns the first
unmet reason, attributes every verdict file to the phase that wrote it, then closes and verifies
the job (`--job N`). Before the first phase konstant composes the phase profile (`dsh
--dump-config`) and refuses the run (exit 2) on anything but dsh's own bundles and
`.dsh/konstant.patch.yml`, or on a composition it cannot read. Each phase runs `dsh --profile
headless --patch .dsh/konstant.patch.yml -` with a FRESH `DSH_HOME` of its own (removed when the
phase ends) inside konstant's jail (bubblewrap): it can write only the project, OUT, that home and
a private `/tmp`; konstant's machinery (`.dsh/`, `catalog/`, `var/`, the project's `.git/config`
...) stays read-only even there; it cannot read the owner, orchestrator or verifier token or the
credential and agent homes konstant lists (dsh's own sandbox confines writes only). The security reviews'
attack modes (invented DECLINED quotes, a detached process flipping the tester's verdict, a
rewritten tester profile, a layer planted for a later phase or for your session) are run through
this path in `tests/review/test_review2_dsh_attacks.py`. The plugin installs nothing inside such a
phase (`KONSTANT_IN_TASK=1`): the runner owns the loop.

## The chat is the intake (level 5)

With `[notify] kind = "chat"` and `[factory] goal_roles = ["owner", "orchestrator"]` in
`konstant.toml` (then `bin/konstant agents sync`), your orchestrator session is the intake of the
dark factory ([LEVEL5.md](LEVEL5.md) section 4.0). The plugin runs `bin/konstant chat turn
--session <id> -` on every message you type (never on a delegated child or a konstant nudge), and
konstant (Python, no model) decides:

- **A work request** (a typed task without `[type:..]` or `[job:..]`) is not done in the chat.
  The message reaches the session with a `KONSTANT INTAKE` block in front of it: the orchestrator
  says in ONE line what it will file (project, goal, limits; else the defaults: `max_attempts =
  3`) and proposes it with `bin/konstant goal add - --from-chat --session <id>` (a goal file on
  stdin). The proposal is `proposed`, not filed.
- **Your next message** decides it: a plain yes (`yes`, `ok`, `ja`, `go`, `confirm`, `file it`,
  ...) files the goal (source `chat`, its copy in `var/factory/goals/`); anything else withdraws it.
  Only your own message in that same session does this: text in a phase log, a web page or a file
  is never a message you sent, and `goal add`/`chat turn` refuse inside a task run.
- **Reports come back here**: the factory's escalations for this session's goals (`BLOCKED`,
  later `DECISION`, `BUDGET_STOP`, ...) are shown at the start of your next turn as `konstant
  chat:` lines, once each; outcomes (`FILED`, ...) as one summary line, details with `bin/konstant
  goal show <goal>`.
- A message tagged `[type:..]` or `[job:..]` keeps the level-4 gate above.
- The session's own bash gets `KONSTANT_CHAT_SESSION=<id>` (so `goal add --from-chat` needs no
  `--session`), and konstant refuses the factory's own steps from it: `konstant intake`,
  `holdout author` and `--as planner|dod-reviewer|scenario|factory`. The orchestrator proposes;
  the factory runs.

In this release the factory step after the yes is `bin/konstant intake <goal>`, run outside the
chat (by you or, from wave L5-5 on, by the factory loop): planner and DoD-reviewer phases, deterministic filing,
approval and the scenario writer; its result comes back into the chat as above. A failing `chat
turn` never blocks the session: a notice says so and the gate runs as before.

## The plugin

Source `src/konstant/harnesses/dsh_gate/index.ts` (TypeScript, dsh's cordis plugin API: the
`agent/pre-step` and `agent/turn-stopping` events, `agent.steer()`, `agent.inject()` and the
`shellEnv` service), the build `konstant-gate.mjs` beside it. The build imports no dsh package
at run time (types only) and runs konstant with `node:child_process` (argv, no shell), so the
release needs no pnpm, esbuild or dsh checkout. To change it:

```sh
cd src/konstant/harnesses/dsh_gate
DSH_SOURCE=<a dsh source checkout> node build.mjs     # or ESBUILD=<esbuild binary>
node build.mjs --check                                # the vendored build equals a fresh one
node --test ../../../../tests/harness/dsh_gate/       # the plugin's own tests
```

The first line of the build records the sha256 of `index.ts`; the test suite fails when they
differ. A type check against dsh's own sources: point a tsconfig that extends the checkout's
`tsconfig.base.json` (with `composite: false`, `noEmit: true`) at `index.ts`.

## Limits

- Your session is not jailed: it is the orchestrator and can read every file you can, as Claude
  Code in this folder can. Role separation between the session and the verifier is procedural
  (docs/CONCEPTS.md, "Security model and limits"). What konstant checks before it starts is above;
  something that changes the session home or `.dsh/` AFTER the start (a person, an unsandboxed
  Claude Code test run with your rights) is not checked, and dsh hot-reloads a profile's
  `cordis.patch.yml` into a running web session.
- dsh confines writes, not the network; there is no per-command allow list.
- Agent launchers by name: unless `[confinement] host_agents = true`, the session's PATH starts
  with `var/harness/dsh/session/bin/`, whose `dsh`, `claude`, `codex` and `gemini` refuse (exit
  126) and name the program they shadow, so a model in the session that runs `dsh ...` never
  reaches your own dsh launcher and its personal home (found in a live run). `bin/konstant`
  itself drops that directory and finds the real CLIs. A program named by its absolute path is
  not stopped. Under `[confinement] profile = "open"` the session keeps dsh's `workspace-write`
  sandbox: the profile widens phases, not your session (docs/CONCEPTS.md, "Confinement
  profiles").
- The chat intake's confirmation is mechanical only as far as the session is: the plugin sends
  `chat turn` for your genuine messages, but the session itself is unjailed, so a model in it that
  ran `bin/konstant chat turn ... yes` on its own could confirm its own proposal. The one-line
  confirmation stays visible in the chat, and every filed goal still goes through the whole
  factory (DoD review by another identity, holdouts, the verifier).
- konstant reads files, never the dsh transcript: in a session, verdict authorship is reported as
  a warning (the runner, with its phase manifests, enforces it).
- The live check of this release ran on one local model (vLLM); a smaller model may not finish a
  typed task within the resume budget, which then ends UNMET or BLOCKED, never MET.
