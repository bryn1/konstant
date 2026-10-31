# konstant

Your agent's "done" is a claim; konstant turns it into a verified result.

```sh
curl -fsSL https://github.com/bryn1/konstant/releases/latest/download/get.sh | bash
```

This installs the latest release into `./konstant` (details: [Install in one line](#install-in-one-line)).

## What konstant is

konstant is a self-contained workspace that sits one layer ABOVE your agent harness (Claude Code,
Codex, Gemini CLI, DeepSeek Harness or any CLI agent). The harness runs the model; konstant never
runs a model loop itself. It decides what the agent does next, in which phases, and whether the
work is actually done, with code that reads artifacts instead of asking a model.

- **Board**: a local job board (FastAPI + SQLite, loopback only) with token roles. A job cannot be
  closed without an executed check (`VERIFY_EXIT=0`), and only the verifier role can mark it
  `verified`, never the identity that closed it.
- **Task gate**: a deterministic classifier maps a task to one of nine task types. Each type runs
  as fixed phases with one agent profile, and verdict files are written by the phases that verify.
- **DoD check**: `konstant task check` applies 13 mechanical Definition-of-Done rules to the files
  a run produced, such as fresh verdicts, a content-hash pin, tests that pass, no stray files and
  honest DONE.md rows. No model is involved. The phase runner resumes the failing phase a bounded
  number of times.
- **Verifier**: `konstant verify` re-checks closed work with allowlisted read-only probes and a
  re-run of the verify command. It passes a job only when a `PROBE:` from the job's DoD (written
  before the work) matched; a re-run or the closer's own probes can fail a job, never pass it.
- **Agents, skills and workflows**: one catalog (`catalog/`) is generated into the files each
  harness reads (`.claude/`, `CLAUDE.md`, `AGENTS.md`, `.agents/skills/`, `.dsh/`, `.gemini/`).

### Harnesses

konstant works above the agent CLI; `--harness` picks the one that runs its phases (without it,
the installer asks on a terminal, otherwise it takes the first one found on PATH):

| `--harness` | runs phases with | models |
|---|---|---|
| `claude` (default) | Claude Code | Anthropic models |
| `codex` | Codex CLI | OpenAI models, or a local OpenAI-compatible server |
| `gemini` | Gemini CLI | Google models |
| `dsh` | DeepSeek Harness | its providers, or a local OpenAI-compatible server; also drives the loop from dsh's own web UI (`bin/konstant dsh web`) |
| `"mycli -p {prompt}"` | the `command` adapter: any CLI that takes a prompt | whatever that CLI reaches |

Local models (vLLM, llama.cpp, Ollama) go through codex or dsh with `[harness.endpoint] base_url`
in `konstant.toml`: [docs/HARNESSES.md](docs/HARNESSES.md), [docs/DSH.md](docs/DSH.md). Any agent
driving konstant finds its operating rules in the generated `AGENTS.md` ("Operating konstant") or,
for Claude Code, `CLAUDE.md`.

### How far it goes on its own

You write the job and its Definition of Done: what must be true, and the probes that prove it.
From there konstant runs unattended: it classifies the task, runs each phase with the right agent
profile, checks the result against the DoD, sends failing work back to the phase that owns the
failure a bounded number of times, closes the job with evidence, and has an independent verifier
re-check it. You come back to a job that is `verified`, or to one that stopped with the reason
written down. You decide what gets built and what "done" means; you do not have to watch the agent
or read its transcript to know whether it finished.

### Documentation

[QUICKSTART](docs/QUICKSTART.md) · [CONCEPTS](docs/CONCEPTS.md) (including the security model and
the two security reviews) · [CLI reference](docs/CLI.md) · [HARNESSES](docs/HARNESSES.md) ·
[DSH](docs/DSH.md) · [DESIGN](docs/DESIGN.md) · [CONTRIBUTING](CONTRIBUTING.md) ·
[SECURITY](SECURITY.md) · [CHANGELOG](CHANGELOG.md)

## Install in one line

```sh
curl -fsSL https://github.com/bryn1/konstant/releases/latest/download/get.sh | bash
```

This installs the latest release into `./konstant`. Pass options after `bash -s --`:

```sh
curl -fsSL https://github.com/bryn1/konstant/releases/latest/download/get.sh | bash -s -- --dir myproj --harness dsh
```

`get.sh` checks for Python >= 3.10, tar, curl or wget and sha256sum or shasum. It downloads
`konstant-<version>.tar.gz` and its `.sha256`, verifies the checksum before unpacking, refuses a
non-empty folder, runs `./install.sh` there and prints the next steps. It never uses sudo and writes
nothing outside the folder. A failed download or a checksum mismatch leaves nothing behind.
Options: `--dir DIR`, `--version V`, `--harness H`, `--port N`, `--wheels DIR`, `--no-install`,
`--yes`. To read the script first, download it, inspect it and run `sh get.sh`; its checksum is
the release asset `get.sh.sha256`.

## Why

An agent's "done" is a claim, not a result. konstant moves the decision about whether work is done
out of the model and into code that reads artifacts. A check that cannot fail is not a check, so
every gate rule ships with a test that must go red. Everything lives in one folder. Uninstall means
deleting the folder.

## Requirements

- Linux or macOS (Windows through WSL2), Python >= 3.10 with `venv` (or `virtualenv`), `git`.
- For agent work: [Claude Code](https://code.claude.com) (`claude` on PATH), or Codex, Gemini CLI,
  DeepSeek Harness or any other CLI agent set in `konstant.toml` (local models through codex or
  dsh: [docs/HARNESSES.md](docs/HARNESSES.md); driving the loop from dsh's own web UI:
  [docs/DSH.md](docs/DSH.md)). The board, the gate, the check and the verifier work without one.
- Optional, recommended with Claude Code on Linux: `bubblewrap` and `socat` (Claude Code's Bash
  sandbox, and konstant's own jail for agent-written tests and dsh phases; `konstant doctor`
  reports both).
  Without them a phase is NOT confined: read
  [CONCEPTS.md, "Security model and limits"](docs/CONCEPTS.md#security-model-and-limits).

## Quickstart (5 minutes)

From a downloaded tarball instead of the one-liner:

```sh
sha256sum -c konstant-0.1.0.tar.gz.sha256         # the .sha256 downloaded next to the tarball
tar xzf konstant-0.1.0.tar.gz && cd konstant-0.1.0
./install.sh --yes                     # venv, package, config, board DB, tokens, agent files, doctor
bin/konstant board start               # the board on 127.0.0.1 (port in konstant.toml)
bin/konstant project add demo --init-git
bin/konstant task classify "Implement a rate limiter; DoD: tests pass?"   # -> code
claude                                 # open Claude Code here; it reads CLAUDE.md and .claude/
```

Inside Claude Code, ask for work as usual. The generated `CLAUDE.md` routes typed tasks through
`konstant task gate` and the per-type workflow. To let konstant drive the phases headless, use:

```sh
bin/konstant task run "[type:code] add a greet() function with a test" --project demo
```

Read [docs/QUICKSTART.md](docs/QUICKSTART.md) next, then [docs/CONCEPTS.md](docs/CONCEPTS.md).
The command reference is [docs/CLI.md](docs/CLI.md); the design is [docs/DESIGN.md](docs/DESIGN.md).

## Task types and agents

| type | agent | delivers |
|---|---|---|
| code | coder | a commit |
| frontend | frontend | a commit |
| infra | infra | a commit |
| test | tester | a verdict |
| security | security | ranked findings + verdict |
| review | reviewer | SHIP / FIX / RECONSIDER |
| research | researcher | a cited document |
| docs | writer | a document |
| design | architect | a design / plan document |

An `orchestrator` profile drives intake, phases and close-out. Verification is built in.

## Layout

```
install.sh            # turns this folder into a workspace (idempotent)
get.sh                # the one-line installer (also a release asset): download, verify, install.sh
bin/konstant          # the CLI wrapper (this folder's venv, this folder as the workspace)
src/konstant/         # package: cli/, board/, gate/, verify/, harnesses/, agents/, release/
catalog/              # types.yaml (the one source), agents/, skills/, workflows/, doctrine/, templates/
release/patterns.toml # public-safety scan patterns (maintainer tooling)
tests/                # unit, board, cli, gate, verify, catalog, release, e2e/
docs/                 # QUICKSTART, CONCEPTS, CLI, HARNESSES, DSH, DESIGN
```

Created by `./install.sh` (git-ignored): `konstant.toml`, `.venv/`, `var/` (board.db, secrets/,
runs/, logs/, backups/), `projects/`, `.claude/`, `CLAUDE.md`, `AGENTS.md` and the surfaces of the
other configured harnesses.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short:

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q          # unit, board, CLI, gate, verify, catalog, release
bash tests/e2e/fresh_install.sh        # build the tarball, install it fresh, run a job lifecycle
bash tests/e2e/one_line.sh             # the same, installed by the one-liner from a local server
```

## License

MIT, see [LICENSE](LICENSE).
