# Quickstart

This walks one job through the board by hand, then one task through the phase runner. Every
command runs from the workspace folder. Run them through `bin/konstant`, which uses this folder's
venv and sets `KONSTANT_HOME` to this folder.

## 1. Install

In one line (the latest release, into `./konstant`; options after `bash -s --`, e.g.
`--dir myproj --harness dsh`; README "Install in one line" lists them):

```sh
curl -fsSL https://github.com/bryn1/konstant/releases/latest/download/get.sh | bash
cd konstant
```

`get.sh` verifies the tarball's sha256 before it unpacks anything, refuses a non-empty folder,
never uses sudo, then runs `./install.sh --yes` (below) with your `--harness`/`--port`/`--wheels`.
Without `--harness` it asks on a terminal (claude, codex, gemini, dsh or any CLI command), else
it takes the first agent CLI on PATH. It also asks for the confinement profile (`--confinement
closed|open`): closed (the default) keeps every phase inside the workspace; open gives phases your
host like your own shell (ssh, docker, your credentials), keeping only the integrity core
([CONCEPTS.md](CONCEPTS.md), "Confinement profiles"). `KONSTANT_RELEASE_URL` points it at a mirror.

Or by hand, from a downloaded tarball:

```sh
tar xzf konstant-0.1.0.tar.gz
cd konstant-0.1.0
./install.sh --yes
```

`install.sh` checks for Python >= 3.10, creates `.venv`, installs the package and writes
`bin/konstant`. It also writes `konstant.toml` (only when absent), creates the board DB and one
token per role in `var/secrets/`, generates the agent files and runs `bin/konstant doctor`. Options:
`--port N` (1024-65535), `--harness "<cmd>"`, `--confinement closed|open` (these apply only to a
new `konstant.toml`; without `--yes` the profile is asked on a terminal),
`--wheels DIR` (offline, from pre-downloaded wheels) and `--from OLD_FOLDER` (upgrade, see
section 7). The installer refuses to run as root.

For an offline install, make the wheel folder on a machine with network, the same Python version
and a current pip (>= 23; an older distribution pip saves nothing useful: run
`python3 -m pip install --user -U pip` first, or use an installed konstant's `.venv/bin/python -m
pip`), then copy it over:

```sh
python3 -m pip download -d wheels ./konstant-0.1.0 setuptools wheel
./install.sh --yes --wheels wheels        # on the offline machine; pip never touches the network
```

(`setuptools wheel` are the build backend konstant itself is built with. A venv that already has
setuptools >= 70.1 builds without them.)

If it stops with *"ensurepip module is missing"*, install your distribution's venv package
(`sudo apt install python3-venv` on Debian/Ubuntu) or `virtualenv`, then re-run it. Re-running is
always safe. It keeps the config, the tokens and the data.

`bin/konstant doctor` exits 0 when no check FAILs. A `WARN` means a reduced capability, for example
no agent CLI on PATH or no OS sandbox. An `INFO` line states a fact, such as the board not running yet.

## 2. Start the board and add a project

```sh
bin/konstant board start               # background server on 127.0.0.1; log in var/logs/board.log
bin/konstant project add demo --init-git
```

Open the read-only web view at the URL `board start` printed. Paste the viewer token from
`var/secrets/viewer.token` when it asks. A project lives in `projects/<slug>/` unless you pass
`--path`. The generated agent files only apply inside this folder.

## 3. A job by hand: add, claim, close, verify

A brief must carry a `DoD:` (or `Acceptance:`) section. `PROBE:` lines are read-only checks the
verifier runs later. The format is `PROBE: <command> => <regex>`, and the commands must have one of
the allowlisted shapes in [CONCEPTS.md](CONCEPTS.md#verifier).

```sh
cat > brief.md <<'B'
Write the project README.

DoD: README.md exists in the project
PROBE: test -e projects/demo/README.md => ^ok$
B
bin/konstant job add "T1: write README" --project demo --type docs --brief brief.md   # JOB=2 ...
bin/konstant job claim 2
echo "# demo" > projects/demo/README.md
printf 'VERIFY_CMD: test -f README.md\nVERIFY_EXIT=0\nDOCS: README.md written\n' > ev.md
bin/konstant job close 2 --evidence ev.md      # -> completed_unverified
bin/konstant verify 2                          # probes + re-run of VERIFY_CMD -> verified
bin/konstant job show 2
```

A close without `VERIFY_EXIT=0`, with a check that checks nothing (`true`, a bare `echo`), or
with output that measured nothing ("Ran 0 tests"), is refused with exit 1 and the reason. If a
probe does not hold, `verify` answers `FAIL` (exit 3) and the job goes back to `queued` with the
finding on its trail. `verify` answers `PASS` only when a `PROBE:` line of the DoD matched: a DoD
without one ends `BLOCKED` ("nothing independent verified"), and `job add` warns about it.

## 4. Let Claude Code work in the workspace

```sh
claude
```

Claude Code reads the generated `CLAUDE.md`, the agents in `.claude/agents/` and the skills in
`.claude/skills/`. Typed work (code, tests, reviews, docs, ...) goes through
`bin/konstant task gate "<task>"`. The gate prints the phases and the verdict files, and
`bin/konstant task check <run>` decides whether the run is done. Accept the folder trust dialog
once. Without it, Claude Code ignores the allow rules in `.claude/settings.json` for interactive
sessions.

## 5. Let konstant drive the phases (headless)

```sh
bin/konstant task run "[type:code] add a greet() function with a test" --project demo
bin/konstant task check var/runs/<the run dir it printed>
```

The runner starts one non-interactive harness run per phase (architect, coder, tester, reviewer,
architect, then the orchestrator close-out for `code`). It runs the DoD check and resumes the
failing phase up to `[gate] max_resumes` times. Exit codes: 0 MET, 3 UNMET, 4 BLOCKED. With
`--job N` the runner also closes the job on MET and runs `konstant verify`.

The default harness is Claude Code, headless and workspace-scoped:

```toml
[harness]
command = "claude -p --permission-mode dontAsk --setting-sources project,local --strict-mcp-config --mcp-config {workspace}/.claude/konstant-mcp.json --add-dir {workspace} --settings {workspace}/.claude/settings.json {prompt}"
```

A phase may read and edit files in this folder (not konstant's own files, `catalog/` or any
`.git/`). It may also run the konstant verbs a phase needs, local git verbs and the test runners
in `[permissions] allow`. Everything else is denied. With the Bash sandbox active (bubblewrap +
socat), that is a boundary. Without it, an allowed test runner executes code the agent wrote with
your rights, so the allow list alone does not confine a phase: see
[CONCEPTS.md](CONCEPTS.md#security-model-and-limits). One task run per project at a time. To let
phases run your project's tests, add the rule and regenerate:

```toml
[permissions]
allow = ["Bash(pytest *)", "Bash(python -m pytest *)", "Bash(python3 -m pytest *)", "Bash(npm test *)"]
```

```sh
bin/konstant agents sync
```

Other harnesses: `[harness] name = "codex"`, `"gemini"`, `"dsh"` (DeepSeek Harness) or
`"command"` (any CLI agent, with your own `[harness] command` and the placeholders `{prompt}` or
`{prompt_file}`, `{workspace}`, `{cwd}`, `{agent}`, `{run_dir}`, `{model}`); `[harness] model`
picks the model; `[harness.endpoint] base_url` points codex or dsh at a local OpenAI-compatible
server (vLLM, llama.cpp, Ollama); `[harness.types.review]` runs the reviewer on another harness
or model. Run `bin/konstant agents sync` after a change and read the `reach` rows of
`bin/konstant doctor`: each harness enforces a different part of the workspace scope, and
[HARNESSES.md](HARNESSES.md) says which. konstant reads the files a phase wrote, never the
transcript.

With dsh you can also drive the loop yourself from dsh's own web UI, tui or headless mode:
`bin/konstant dsh web` starts dsh with konstant's task-gate plugin, which gates every typed
message, runs the DoD loop at the end of the turn and, for a job (`[job:N]` in the message),
closes it and runs `konstant verify` ([DSH.md](DSH.md)).

## 6. Memory

Every harness konstant starts gets a memory server (`bin/konstant mcp memory`; tools `kb_recall`,
`kb_store`, `kb_note`); you and any other agent use the same memory from the shell:

```sh
bin/konstant memory store "The demo project greets in lower case." --tag demo
bin/konstant memory recall greets                 # lexical, or hybrid with an embedding endpoint
bin/konstant memory note "Greeter design" - < notes.md   # a named note; [[links]] and #tags work
bin/konstant memory list                          # recent notes; `memory log`: who wrote what
```

The notes are plain Markdown in `memory/` (its own git history: `git -C memory log`), so you can
open that folder in Obsidian. For hybrid recall, point `[memory] embed_endpoint` and
`embed_model` at a local OpenAI-compatible embedding server. The board's web view has a
read-only Memory tab. What phases may see of it, and why the scenario writer and the verifier
keep their notes to themselves: [CONCEPTS.md](CONCEPTS.md), "Memory".

## 7. Everyday commands

```sh
bin/konstant job list --tree           # the board as a tree
bin/konstant job search "readme"       # prior work before filing new work
bin/konstant verify --pending          # verify every completed_unverified job
bin/konstant board backup              # online copy into var/backups/
bin/konstant agents list               # types, agents, skills, workflows
bin/konstant doctor
```

Full reference: [CLI.md](CLI.md).

## 8. Upgrade and uninstall

Unpack the new release next to the old folder, stop the old board, then:

```sh
cd konstant-<new>
./install.sh --yes --from ../konstant-0.1.0   # backs up the old DB, copies konstant.toml, var/, projects/, memory/
```

To uninstall, run `bin/konstant board stop` and delete the folder. konstant writes nothing outside it.
