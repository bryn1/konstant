# Harnesses: any agent CLI, any model

konstant is the layer **above** the harness. It never runs a model loop itself: a phase is one
headless run of an agent CLI, and the model belongs to that CLI. "Any model" therefore means
first-class adapters for several harnesses, each of which reaches its own models; local models
come in through the harnesses that speak an OpenAI-compatible API (DeepSeek Harness and Codex).

Whatever the harness, konstant's own guarantees hold, because none of them depends on the
harness: a phase acts as `worker` (`KONSTANT_ROLE=worker`; the CLI refuses every other token),
the runner reaps every process a phase leaves running (Linux subreaper), `task check` and
`verify` run agent-written code in konstant's bubblewrap jail (`[gate] jail`), verdict files are
pinned, and the DoD check reads files, never a transcript. What differs per harness is what the
harness itself lets a phase do. This page states that plainly; `bin/konstant doctor` prints the
same verdicts for the harnesses you configured.

## Choosing a harness

```toml
[harness]
name = "claude"        # claude | codex | gemini | dsh | command
model = ""             # passed through the harness's own model key; "" = its default
# command = "..."      # your own argv template; required for name = "command"
timeout_s = 3600
max_parallel = 2
env = {}               # extra environment for every phase (wins over the adapter's)
env_passthrough = []   # host variables (NAME or NAME*) a closed phase also keeps: a closed
                       # phase's env is an allowlist (PATH, HOME, locale, KONSTANT_*, the
                       # harness's model keys, api_key_env below); every other host variable
                       # is dropped (docs/CONCEPTS.md "Security model and limits")

[harness.endpoint]     # a local OpenAI-compatible server, for codex and dsh
base_url = ""          # e.g. "http://127.0.0.1:8000/v1" (vLLM), ":11434/v1" (Ollama), ":8080/v1" (llama.cpp)
api_key_env = ""       # the variable that holds its key; "" = none needed

[harness.types.review] # per task type: the phases of that type's agent run here
name = "codex"         # e.g. the reviewer on another harness or model than the coder
model = "gpt-5.4-mini"
```

- A phase runs on the harness of its agent's type (`catalog/types.yaml` maps each agent to one
  type, so `[harness.types.review]` moves the `reviewer` phases of every task, not only of review
  tasks). The close-out (orchestrator) runs on the default. Each phase manifest
  (`var/runs/<run>/phases/*.json`) records `harness` and `model`.
- A per-type row that keeps the default harness inherits its model and command; a row that names
  another harness starts from that harness's defaults.
- `command` replaces the adapter's own command (placeholders `{prompt}`, `{prompt_file}`,
  `{workspace}`, `{cwd}`, `{agent}`, `{run_dir}`, `{model}`). konstant then cannot vouch for its
  reach (`doctor` says so). A `model` with a custom command needs `{model}` in it.
- `bin/konstant task run --harness "<cmd>"` runs every phase of that run with one template.
- After changing `[harness]`, run `bin/konstant agents sync`: it writes the surfaces of the
  configured harnesses only and removes the generated files of a harness you dropped.
  `agents sync --check [--harness NAME]` reports drift per harness (`doctor` runs it).
- `./install.sh --harness codex` (or `claude`, `gemini`, `dsh`) writes `name = ...` into a new
  `konstant.toml`; any other value is written as `command`.

## The matrix

Design decision (workspace-scoped reach): a phase may edit files and run commands **only inside the workspace**; the
rest is denied. "Enforced" means the harness's own permission system does it with konstant's
generated configuration; "partial" and "none" are the limits you accept with that harness.

| harness | surfaces it reads (generated) | edits | commands | reads | user-level config | local models | tested live |memory (`konstant mcp memory`) |
|---|---|---|---|---|---|---|---|---|
| `claude` (Claude Code 2.1.x) | `CLAUDE.md`, `.claude/agents/`, `.claude/skills/`, `.claude/settings.json` | enforced | enforced with the Bash sandbox (bubblewrap + socat); partial without it | enforced (sandboxed); partial without the sandbox | settings, hooks, MCP skipped; `~/.claude/CLAUDE.md` memory still loads | Anthropic API only (an Anthropic-compatible gateway via `ANTHROPIC_BASE_URL`; not tested) | **yes** (haiku) |`--mcp-config .claude/konstant-mcp.json` (the only MCP server under `--strict-mcp-config`), tools allowed by name |
| `codex` (codex-cli 0.142.x) | `AGENTS.md`, `.agents/skills/` | enforced | partial: no allow list, but every command runs inside the same file boundary; network on | enforced: privileged tokens, the credential and agent homes konstant lists, `~/.codex/auth.json` unreadable | `config.toml` + execpolicy rules skipped; `~/.codex/AGENTS.md` and user skills may still load | yes: `[harness.endpoint]` -> a Responses-API provider (vLLM, Ollama, llama.cpp) | sandbox **yes** (no model); model run **NOT RUN** (account refused every model) |`-c mcp_servers.konstant-memory...` on the exec line, `enabled_tools`, approval `approve` |
| `gemini` (Gemini CLI) | `AGENTS.md` (as context file), `.agents/skills/`, `.gemini/settings.json`, `.gemini/konstant-policy.toml` | enforced (edit tools confined to the workspace dirs; machinery denied by policy) | partial: policy allow list, the rest denied headless; an allowed test runner is unsandboxed unless `--sandbox` (Docker/Podman) | partial: file tools confined; allowed commands read anything | enforced: `GEMINI_CLI_HOME` relocated | no (Gemini API only) | **NOT RUN** (not installed here) |`mcpServers` in `.gemini/settings.json` + `mcpName` policy rules |
| `dsh` (DeepSeek Harness 0.2.x) | `AGENTS.md`, `.agents/skills/`, `.dsh/konstant.patch.yml` (+ for your own session: `.dsh/konstant-session.patch.yml`, `.dsh/konstant-gate.mjs`, `.dsh/agents/`; [DSH.md](DSH.md)) | enforced (writes only under the project dir, OUT + a private `/tmp`; in the jail konstant's machinery and the project's `.git/config`/`.git/hooks` read-only) | partial: no allow list; network open | enforced by konstant's jail: owner/orchestrator/verifier tokens and the credential and agent homes konstant lists (`~/.ssh`, `~/.dsh`, `~/.codex`, `~/.claude`, ...; [CONCEPTS.md](CONCEPTS.md)) unreadable; other files in your home readable. **none** without a working bubblewrap or with `[gate] jail = false` | enforced: a fresh `DSH_HOME` + `DSH_AGENTS_HOME` per phase; a run starts only on dsh's own bundles + konstant's patch (fail closed) | yes: `[harness.endpoint]` -> an `openai-completions` provider | **yes** (local endpoint; token read denied live) |an `@deepseek-ai/dsh-mcp-client` row in `.dsh/konstant.patch.yml` |
| `command` (any CLI) | `AGENTS.md`, `.agents/skills/` (if the tool reads them) | none known | none known | none known | the tool's own | whatever the tool supports | via the fake harness in the test suite and the e2e |the CLI: `bin/konstant memory recall\|store\|note` |

Every adapter keeps konstant's machinery out of a phase's reach with whatever its permission
system offers, from ONE list (`src/konstant/machinery.py`: `bin/`, `src/`, `catalog/`, `tests/`,
`konstant.toml`, the generated surfaces of EVERY harness `.claude/` `.agents/` `.dsh/` `.gemini/`
`AGENTS.md` `CLAUDE.md`, `var/harness/`, `var/secrets/`, the board DB, `.git/`): Claude Code deny
rules + sandbox `denyWrite`, the codex profile (read-only), the gemini policy (deny), and
konstant's jail for dsh (read-only binds, even inside the project or the workspace). A test
checks that each entry has a rule in each of them. So a phase of one harness cannot rewrite what
another harness, or your own session, loads later.

The sealed holdout store `var/holdout/` (`machinery.SEALED`; [CONCEPTS.md](CONCEPTS.md),
"Holdouts") is denied for READS the same way: Claude Code `Read` deny + sandbox `denyRead`, codex
`deny`, a gemini policy rule denying `read_file`, `read_many_files`, `glob` and
`search_file_content` under it, and an empty tmpfs over it in konstant's jail. Commands are only
covered by the jail, so a job with holdouts runs in **factory mode**: konstant jails every phase
of it on every harness (claude, codex, gemini, dsh and a `command` template), with only the
phase identity's token and the viewer token readable, writes limited to the job's clone, OUT, a
private TMPDIR and a fresh per-phase harness home (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`,
`GEMINI_CLI_HOME`; only the CLI's own credential file is bound in, read-only), and the project
itself read-only. The harness's own sandbox runs nested inside; for Claude Code that needs a nested
bubblewrap, socat and the jail's private `/tmp` (else its sandbox is switched off for the phase
and the jail is the boundary; `doctor` row `claude sandbox`). Without a working jail such a job
refuses to start (exit 2).

Read "none" and "partial" literally. With `codex` and with `dsh` (inside konstant's jail) a phase
cannot read the privileged tokens, but any command may run inside the file boundary and the
network is open; without the jail a `dsh` phase can read `var/secrets/` and act on the board
with the orchestrator token. Treat "partial" as "role separation inside a phase is procedural"
(docs/CONCEPTS.md, "Security model and limits").

## Confinement profiles: closed and open

The matrix above is the **closed** profile, the default. `[confinement] profile = "open"` gives a
phase the host like your own shell (read and write anywhere you can, network, ssh and your ssh
agent, the docker socket, your credential files and variables), and per-capability options
override either profile ([CONCEPTS.md](CONCEPTS.md), "Confinement profiles", has the table with
what each allows and risks). `bin/konstant confinement show` prints, for each configured harness,
how each option is enforced at level 4 and in factory mode.

| harness | how the profile and its options map |
|---|---|
| `claude` | generated `.claude/settings.json`: open adds `Bash`, `Read(//**)` and drops `blockReadsOutsideWorkingDirectories`; `host_write`/`home_write` -> `Edit(//**)`/`Edit(~/**)` + sandbox `allowWrite`; `extra_read`/`extra_write` -> Read/Edit rules + `additionalDirectories`; passed credentials leave the sandbox `denyRead`; `home_read = false` -> sandbox `denyRead ~/`; `network` -> `sandbox.network.allowedDomains`; `ssh_agent` -> `allowAllUnixSockets`; `docker_socket` -> `allowUnixSockets` (keys from Claude Code's settings schema; the open rendering was not run against a live Claude Code) |
| `codex` | the `konstant` permission profile: `:root = write` (`host_write`), `$HOME = write`, deny rules for `home_read = false`, write/read rules for the extra paths, passed credentials not denied, `network.enabled` from `network`; sockets cannot be named (the jail handles them when it wraps the phase) |
| `gemini` | the generated policy: open allows every shell command (priority 50, below every deny); `extra_*` -> `--include-directories`; its shell is otherwise only confined by konstant's jail |
| `dsh` | the generated patch: `danger-full-access` (sandbox, preset, `DSH_PERMISSION_MODE`) when phases may write outside their project, konstant's jail being the boundary (a run refuses when the jail cannot wrap the phase); your own `konstant dsh` session stays `workspace-write` |
| `command` | konstant's jail only |

**Every profile keeps the integrity core**: the holdout store unreadable, only the phase's own
identity token (and viewer's) readable, konstant's machinery (the list above) not writable, and
in factory mode the target and the other job clones read-only. Under open, konstant therefore
runs every phase of every harness in its jail at level 4 too, as a thin layer: the host root bound
writable, masks and read-only binds over the core only. The rules each harness renders for the
core (deny rules, profile denies, policy denies) stay as well. With `integrity = "off"` (open,
level 4 only) none of that applies and `doctor` FAILs; factory mode refuses to start.

## Memory: one MCP server for every harness

konstant ships ONE memory server, `bin/konstant mcp memory` (MCP over stdio, standard library
only; tools `kb_recall`, `kb_store`, `kb_note`), and `agents sync` wires it into each configured
harness from one description (`src/konstant/memory/wiring.py`). The server talks to the board
with the phase identity's token, so the board decides pools and refusals the same way for
every harness ([CONCEPTS.md](CONCEPTS.md), "Memory"); the vault itself is unreadable to phases on
every harness (`memory/` is in `machinery.SEALED`). `[memory] enabled = false` renders none of it.

| harness | how the server is wired | how the phase's identity reaches it | checked |
|---|---|---|---|
| `claude` | `.claude/konstant-mcp.json` passed with `--mcp-config` (in the default command, beside `--strict-mcp-config`, so it is the only MCP server a phase loads); `mcp__konstant-memory__kb_recall`, `..._kb_store`, `..._kb_note` in the allow list (under `dontAsk` any other MCP tool is denied) | inherited environment (`KONSTANT_IN_TASK`, `KONSTANT_IDENTITY`, `KONSTANT_RUN`); the config sets `KONSTANT_HOME` | settings and argv golden; the server's handshake in the e2e; a real `claude -p` (2.1.x) with the default command, scripted by a loopback stand-in for the Messages API (no model call): it loaded the server, offered the three tools as deferred tools (loaded with ToolSearch), allowed them under `dontAsk`, `kb_recall` returned a shared note and `kb_store` wrote one attributed to `worker` |
| `codex` | `-c mcp_servers.konstant-memory.command/args/env_vars/enabled_tools/default_tools_approval_mode="approve"` on the `codex exec` line (`--ignore-user-config` still drops your own servers) | `env_vars` forwards the five `KONSTANT_*` variables | `codex mcp list` (0.142.5, scratch `CODEX_HOME`) parses the keys and lists the server; the approval enum is `auto`/`prompt`/`approve`; a model run **NOT RUN** |
| `gemini` | `mcpServers.konstant-memory` (`includeTools` = the three tools) in the generated `.gemini/settings.json`; policy rules `mcpName = "konstant-memory"` + `toolName` allow each tool (the server name has no underscore: Gemini CLI's policy parser splits on it) | `env` in the settings with `$KONSTANT_...` references (Gemini CLI strips variables from an MCP server's environment unless named) | golden; **NOT RUN** live (not installed here) |
| `dsh` | an inserted `@deepseek-ai/dsh-mcp-client` row (`serverName: konstant-memory`, stdio) in `.dsh/konstant.patch.yml`; your own `konstant dsh` session composes the same patch | inherited environment (dsh's bridge drops only `*KEY*`/`*TOKEN*`/`*SECRET*`/`*PASSWORD*` names and `DSH_*`) | golden; the real dsh 0.2.1 `--dump-config` (scratch `DSH_HOME`) composes the row from konstant's patch; a model run **NOT RUN** |
| `command` | none: the tool reads `AGENTS.md`, which names the CLI fallback | the phase environment | the CLI in the test suite |

The scenario writer reads the shared pool and writes the sealed one without holding a token: its
server runs in VIEW mode (`KONSTANT_MEMORY_VIEW`, `KONSTANT_MEMORY_OUT`, set by konstant for that
phase only) on a copy konstant exported into its drafts dir; konstant stores its notes into the
sealed pool after the phase (`src/konstant/memory/view.py`). Outside that mode the server refuses
the `scenario` identity.

## Adapters

Each default command below was checked against the installed tool's `--help` and its official
documentation (sources at the end). Rendered for a workspace `<workspace>`:

### claude

```
claude -p --permission-mode dontAsk --setting-sources project,local --strict-mcp-config --add-dir <workspace> --settings <workspace>/.claude/settings.json [--model M] <prompt>
```

Unchanged from v0.1 (DESIGN §9): the generated `.claude/settings.json` is the whole reach under
`dontAsk`; deny rules for konstant's machinery, every `.git/`, `var/secrets/` and the verbs of
other roles; the Bash sandbox when bubblewrap and socat are present. `model` becomes
`--model` (an alias such as `haiku` or a full model id).

### codex

```
codex exec --ignore-user-config --ignore-rules --skip-git-repo-check --ephemeral --color never
  -c approval_policy="never" -c default_permissions="konstant"
  -c permissions.konstant.filesystem={...} -c permissions.konstant.network.enabled=true
  -c project_root_markers=["konstant.toml"] -c history.persistence="none" [-m M] -
```

The prompt goes on stdin (`-`). The permission profile `konstant` is rendered per phase: the
whole file system `read`, the workspace `write`; read-only: `bin/`, `.venv/`, `src/`, `catalog/`,
`tests/`, `.claude/`, `.agents/`, `.dsh/`, `.gemini/`, `konstant.toml`, `install.sh`,
`pyproject.toml`, `AGENTS.md`, `CLAUDE.md`, all of `var/`, and the `.git/config` and `.git/hooks/`
of the workspace and every project; `deny` (unreadable): the owner, orchestrator and verifier
tokens, `~/.ssh`, `~/.aws`, `~/.gnupg`, ... and `~/.codex/auth.json`; `write` again: the run's
OUT and its private TMPDIR. `/tmp` is not writable (konstant sets `TMPDIR` to the run's `tmp/`).
Only paths that exist are named: bubblewrap cannot create a mount point inside a read-only tree
(observed live with the board's `-shm` file). Network stays on because the konstant CLI talks to
the loopback board. `approval_policy = "never"` returns a denied call to the model instead of
escalating. `--ignore-user-config` skips `~/.codex/config.toml` (MCP servers, hooks, profiles,
project trust), so no project-level `.codex/` layer loads either (it needs trust);
`--ignore-rules` skips execpolicy `.rules` files. `project_root_markers = ["konstant.toml"]`
makes the workspace the project root, so the workspace `AGENTS.md` loads in a project
sub-directory.

Local models: with `[harness.endpoint] base_url`, konstant adds
`-c model_providers.konstant={name, base_url, wire_api="responses", env_key}` and
`-c model_provider="konstant"`; `[harness] model` is the served model name. Codex speaks only the
Responses API, which vLLM, Ollama and recent llama.cpp servers serve at `/v1/responses`.

### gemini

```
gemini --approval-mode auto_edit --policy <workspace>/.gemini/konstant-policy.toml
  --include-directories <workspace> --output-format text [-m M] -p "Carry out the konstant phase given above."
```

The phase prompt goes on stdin (`-p` is appended to it and forces non-interactive mode).
`auto_edit` approves the edit tools, which Gemini CLI confines to the workspace directories (the
cwd + `--include-directories`). The generated policy file (passed with `--policy`: Gemini CLI
disables workspace-tier policies) allows `run_shell_command` only for the konstant verbs a phase
needs, the local git verbs, the workspace's pytest and the `Bash(<cmd> *)` rules of
`[permissions] allow`; denies the verbs of other roles, `--as owner|verifier`, and edits to
konstant's machinery, `var/` (except a run's OUT) and any `.git/`; in non-interactive mode every
other call (`ask_user`) is denied. `GEMINI_CLI_HOME` points into `var/harness/gemini/`, so your
`~/.gemini` settings, `GEMINI.md`, policies, extensions and MCP servers never load; konstant copies
the generated `.gemini/settings.json` (`context.fileName = ["AGENTS.md"]`,
`loadMemoryFromIncludeDirectories = true`) into that home. Auth: `GEMINI_API_KEY` (or the Vertex
variables) in the environment; an OAuth login in `~/.gemini` is not visible to a phase (put
`GEMINI_CLI_HOME = "<your home>"` in `[harness] env` to use it, and accept that your user-level
Gemini config then loads too). Not exercised against a real install: implemented from the docs and
source listed below; its live smoke is **NOT RUN**.

### dsh (DeepSeek Harness)

```
dsh --profile headless --patch <workspace>/.dsh/konstant.patch.yml -
```

The prompt goes on stdin. The generated patch sets `sandbox-policy` to `workspace-write` (on
Linux bubblewrap/Landlock; the write root is the session cwd = the project dir, plus a private,
empty `/tmp`), `approval` to `never` (a sandbox escalation is rejected, never asked), a
permission preset `konstant` = (workspace-write, never) as the default (dsh refuses to start its
preset selector otherwise), `agent-instructions` with the root marker `konstant.toml`, and
`skill-filesystem` with `.agents/skills` of the workspace as the only skill root. `DSH_HOME` and
`DSH_AGENTS_HOME` point into `var/harness/dsh/`, so your own dsh profiles, credentials, MCP
servers, `AGENTS.md` and skills never load. Each phase gets a FRESH `DSH_HOME` and
`DSH_AGENTS_HOME` (`var/harness/dsh/phases/<label>-XXXX/`, removed when the phase ends), so a
profile layer one phase writes there never loads into a later phase. With `[harness.endpoint]` the patch adds an
`llm-pi-ai` provider `konstant` (`openai-completions`) listing every dsh model in `konstant.toml`
and makes it the default; the model is chosen per phase through `KONSTANT_MODEL`.

Limits, from dsh's own documentation: its sandbox governs file **writes** only; reads and the
network are not confined, and there is no per-command allow list. konstant therefore starts every
dsh phase inside its own bubblewrap jail (`konstant.jail`, the one that runs agent-written tests):
the root read-only, writes only to the project dir, the run's OUT, the phase's own fresh dsh
home and a private `/tmp`, konstant's machinery read-only even inside those (a phase started in
the workspace itself cannot write `catalog/`, `.dsh/`, `var/` ...), the project's `.git/config`
and `.git/hooks` read-only, `var/secrets/` masked except the worker and viewer tokens, the
credential and agent homes konstant lists masked, an own pid namespace. dsh's sandbox runs nested inside it (checked live: the
orchestrator token read failed with "No such file or directory", the worker token was read, a
write outside was denied, `bin/konstant job list` ran). Without a working `bwrap` or with
`[gate] jail = false` the phase runs unjailed and `doctor` reports `reads none`. Your own dsh
session (`bin/konstant dsh`, [DSH.md](DSH.md)) is the orchestrator and is not jailed.
Two more found live:
- A workspace under `/tmp` does not work: dsh's sandbox replaces `/tmp` with an empty private
  one, so a phase cannot see `bin/konstant`. `doctor` WARNs.
- A launcher script that exports its own `DSH_HOME` defeats the relocation and loads the
  operator's profile into every phase. Before the first phase of a run, and in `doctor`, konstant
  composes the profile like a phase does (`dsh --dump-config`, no model call) and judges the
  RESULT: every layer must be one of dsh's shipped bundles (as a fresh, empty home composes them)
  or `.dsh/konstant.patch.yml`; an id-patch or insert-only layer from anywhere else, a bundle a
  profile added, or a home dsh did not use is refused (doctor FAIL, the run exits 2), and so is a
  composition it cannot read (a dsh on Node 20 prints nothing and exits 0).

### command (any other CLI)

`[harness] name = "command"` and an argv template. konstant generates `AGENTS.md` and
`.agents/skills/`; the reach is whatever the tool enforces (`doctor` WARNs). Examples, flags from
each tool's documentation (not installed or tested here):

```toml
[harness]
name = "command"
command = "opencode run --model {model} {prompt}"        # `opencode run [message..]`
model = "provider/model"
```

```toml
[harness]
name = "command"
command = "aider --yes-always --no-auto-commits --openai-api-base http://127.0.0.1:8000/v1 --model {model} --message-file {prompt_file}"
model = "openai/served-name"
```

## Local models

The path: a local OpenAI-compatible server (vLLM, llama.cpp `llama-server`, Ollama) ->
`[harness.endpoint]` -> `dsh` (Chat Completions) or `codex` (Responses API). Example:

```toml
[harness]
name = "dsh"
model = "my-coder-model"     # the name the server serves (GET /v1/models)

[harness.endpoint]
base_url = "http://127.0.0.1:8000/v1"
api_key_env = ""                               # dsh gets a placeholder key; a server ignores it
```

Mixed setups work per type, e.g. the coder on a local model through dsh and the reviewer on a
cloud model through Claude Code (`[harness.types.review] name = "claude"`). The endpoint applies
to every codex and dsh phase.

`task run --harness dsh` (an adapter name) runs every phase of that run on dsh whatever the
toml's per-type rows say; `--harness "<argv template>"` is unchanged.

## Verifying it yourself

- `bin/konstant doctor`: one `harness` row per configured harness (found on PATH, version),
  one `reach` row each (what is enforced, and every limit in words), `dsh layers` / `dsh /tmp`
  for dsh, the Claude sandbox row, the jail row.
- `bin/konstant agents sync --check --harness NAME`.
- A live smoke per harness (one cheap headless phase: an allowed `bin/konstant job list`, a write
  outside the workspace with the file tool and with the shell, a write inside the project) needs
  the harness and a model, so it is run by hand, not by the test suite.

## Sources

Checked against (October 2026): `claude --help` (2.1.314), `codex --help`,
`codex exec --help`, `codex sandbox --help` (codex-cli 0.142.5), `dsh --help`,
`dsh headless --help` (0.2.1-alpha.3).

- Claude Code: settings, permissions, sandboxing and CLI reference at code.claude.com/docs (as
  cited in DESIGN §9).
- Codex: developers.openai.com/codex/config-reference (sandbox, `approval_policy`,
  `model_providers.<id>.{base_url,env_key,wire_api}`, `project_root_markers`, `default_permissions`,
  `permissions.<name>.filesystem`), developers.openai.com/codex/permissions (path tokens, `deny`
  reads, profiles vs `sandbox_mode`), developers.openai.com/codex/skills (`.agents/skills` scopes).
- Gemini CLI (github.com/google-gemini/gemini-cli, main): docs/cli/cli-reference.md,
  docs/cli/headless.md, docs/reference/policy-engine.md (workspace tier disabled, `ask_user` =
  deny in non-interactive mode, rule fields), docs/tools/file-system.md, docs/cli/skills.md
  (`.agents/skills` alias), packages/cli/src/config/config.ts (`--policy`, `--admin-policy`,
  `--approval-mode`, `--include-directories`), packages/cli/src/config/settings.ts and
  settingsSchema.ts (`context.fileName`, `context.loadMemoryFromIncludeDirectories`),
  packages/core/src/utils/paths.ts (`GEMINI_CLI_HOME`).
- DeepSeek Harness (MIT, github.com/deepseek-ai/deepseek-harness): docs/cli-help.md,
  docs/subsystems/{sandbox,approval,permission-presets}.md, docs/user/guide/providers.md,
  packages/context/agent-instructions/README.md, packages/skill/skill-filesystem/README.md,
  packages/shell/bash-sandbox/README.md, packages/sandbox/sandbox-local/README.md.
- aider: aider.chat/docs/config/options.html. opencode: opencode.ai/docs/cli.
