"""Harness runner (DESIGN §9): run ONE phase with any CLI agent, never through a shell.

The adapters (claude, codex, gemini, dsh, command) live in konstant/harnesses/ and
docs/HARNESSES.md; this module starts the process, logs it, times it out and kills it.

`[harness] command` is an argv template split with shlex. Placeholders: {prompt} (the whole
prompt as one argv item; refused over 100 KiB - use {prompt_file} or stdin = true),
{prompt_file} (a 0600 file in the run dir), {agent}, {cwd}, {run_dir}, {workspace}, {model}. The
process runs in the project dir in its own process group with KONSTANT_IN_TASK=1, KONSTANT_RUN,
KONSTANT_ROLE=worker and KONSTANT_HOME; stdout+stderr go to phases/<label>.log. konstant reads
files, never the harness's transcript, so any CLI agent works.

Default (design decision: workspace-scoped permissions; every name checked against the installed
`claude --help` and the official permission docs, see DESIGN §9):
  claude -p --permission-mode dontAsk --setting-sources project,local --strict-mcp-config
         --add-dir {workspace} --settings {workspace}/.claude/settings.json {prompt}
`-p` = non-interactive; `dontAsk` denies every call that would prompt, so only the allow rules
of the generated workspace settings run and anything else fails the phase instead of reaching
outside; `--settings` passes those rules explicitly because a `-p` run never applies the allow
rules of an untrusted project's `.claude/settings.json` and a phase runs in a project
sub-directory, where Claude Code does not look for the workspace's `.claude/` at all;
`--setting-sources project,local` keeps the operator's user-level settings and hooks out of a
phase and `--strict-mcp-config` their MCP servers (REVIEW F-20; user-level CLAUDE.md memory is
not a settings source - docs/CONCEPTS.md "Security model and limits");
`--add-dir {workspace}` makes the workspace a working directory (readable under
blockReadsOutsideWorkingDirectories, writable inside the sandbox) and loads its generated
`.claude/agents` and `.claude/skills`. `--add-dir` takes several values, so it must stand before
another option, never directly before {prompt}.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from konstant import harnesses
from konstant.harnesses.base import (ARGV_PROMPT_MAX, PLACEHOLDERS, HarnessError, Phase,
                                     build_argv)

__all__ = ["ARGV_PROMPT_MAX", "PLACEHOLDERS", "DEFAULT_COMMAND", "Harness", "HarnessError",
           "HarnessSet", "PhaseResult", "build_argv", "from_choice", "kill_all"]

DEFAULT_COMMAND = harnesses.DEFAULT_COMMAND      # the one source is config.DEFAULTS
_ACTIVE: set = set()
_LOCK = threading.Lock()


def _child_umask() -> int:
    """The caller's own umask for a phase (konstant's CLI runs with 077 for its own files)."""
    from konstant import config
    return config.ORIG_UMASK if config.ORIG_UMASK is not None else -1


@dataclass
class PhaseResult:
    rc: int
    seconds: float
    log: str
    timed_out: bool = False


def kill_all(sig: int = signal.SIGTERM, grace: float = 5.0) -> int:
    """Stop every running harness process group (used by the runner's signal handler)."""
    with _LOCK:
        procs = list(_ACTIVE)
    for p in procs:
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.time() + grace
    for p in procs:
        try:
            p.wait(max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    return len(procs)


class Harness:
    """One harness: an explicit argv template (`command`), or an adapter's own command
    (`adapter`, with `command` None)."""

    def __init__(self, command: str | None, *, stdin: bool = False, timeout_s: int = 3600,
                 env: dict | None = None, workspace: Path, adapter=None, model: str = "",
                 endpoint: dict | None = None, allow: list | None = None, name: str = "",
                 jail: bool = True):
        self.command, self.stdin, self.timeout_s = command, stdin, timeout_s
        self.jail = jail
        self.env, self.workspace = dict(env or {}), Path(workspace)
        self.adapter, self.model = adapter, model
        self.endpoint, self.allow = dict(endpoint or {}), list(allow or [])
        self.name = name or (adapter.name if adapter is not None else "command")

    def phase(self, values: dict) -> Phase:
        return Phase(values, model=self.model, endpoint=self.endpoint, allow=self.allow,
                     jail=self.jail)

    def argv(self, values: dict) -> list:
        if self.command is not None:
            return build_argv(self.command, {**values, "model": self.model}, self.stdin)
        return self.adapter.argv(self.phase(values))

    def check(self, run_dir: Path | None = None) -> None:
        """Fail fast on a template that cannot work (before any phase starts)."""
        rd = Path(run_dir or self.workspace / "var" / "runs" / "-")
        self.argv({"prompt": "", "prompt_file": rd / "prompts" / "x.md", "agent": "-",
                   "cwd": self.workspace, "run_dir": rd, "workspace": self.workspace})
        if self.command is None and self.adapter is not None:
            why = self.adapter.preflight(self.workspace)
            if why:
                raise HarnessError(why)

    def run(self, prompt: str, *, agent: str, cwd: Path, run_dir: Path, label: str,
            out: Path | None = None) -> PhaseResult:
        prompts = Path(run_dir) / "prompts"
        prompts.mkdir(parents=True, exist_ok=True)
        pfile = prompts / f"{label}.md"
        fd = os.open(pfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        values = {"prompt": prompt, "prompt_file": pfile, "agent": agent, "cwd": cwd,
                  "run_dir": run_dir, "workspace": self.workspace, "out": out}
        argv = self.argv(values)
        extra, ph = {}, None
        if self.command is None and self.adapter is not None:
            ph = self.phase(values)
            self.adapter.prepare(ph)
            extra = self.adapter.env(ph)
            argv = self.adapter.confine(argv, ph)
        try:
            return self._start(argv, extra, prompt, cwd, run_dir, label)
        finally:
            if ph is not None:
                self.adapter.cleanup(ph)       # e.g. dsh's per-phase home: nothing persists

    def _start(self, argv: list, extra: dict, prompt: str, cwd: Path, run_dir: Path,
               label: str) -> PhaseResult:
        logs = Path(run_dir) / "phases"
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / f"{label}.log"
        env = {**os.environ, **extra, **{k: str(v) for k, v in self.env.items()},
               "KONSTANT_IN_TASK": "1", "KONSTANT_RUN": str(run_dir), "KONSTANT_ROLE": "worker",
               "KONSTANT_HOME": str(self.workspace)}
        t0, timed_out = time.time(), False
        with open(log, "wb") as fh:
            try:
                proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=fh,
                                        stderr=subprocess.STDOUT, start_new_session=True,
                                        stdin=subprocess.PIPE if self.stdin else subprocess.DEVNULL,
                                        umask=_child_umask())
            except OSError as exc:
                fh.write(f"konstant: could not start the harness {argv[0]!r}: {exc}\n".encode())
                return PhaseResult(127, 0.0, str(log))
            with _LOCK:
                _ACTIVE.add(proc)
            try:
                proc.communicate(prompt.encode() if self.stdin else None, timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
            finally:
                with _LOCK:
                    _ACTIVE.discard(proc)
        rc = 124 if timed_out else proc.returncode
        return PhaseResult(rc, round(time.time() - t0, 3), str(log), timed_out)


def from_choice(choice, hcfg: dict, workspace: Path, allow: list | None = None,
                jail: bool = True) -> Harness:
    """An explicit template (yours, or name = "command") runs as written; otherwise the
    adapter renders the argv, env and per-phase preparation."""
    return Harness(choice.template, stdin=choice.stdin, timeout_s=hcfg["timeout_s"],
                   env=hcfg["env"], workspace=workspace,
                   adapter=None if choice.template is not None else choice.adapter,
                   model=choice.model, endpoint=hcfg.get("endpoint"), allow=allow,
                   name=choice.name, jail=jail)


class HarnessSet:
    """The harness of each phase: its agent's type override, else the default (DESIGN §9)."""

    def __init__(self, hcfg: dict, workspace: Path, cat=None, allow: list | None = None,
                 override: str | None = None, jail: bool = True):
        self.cat = cat
        if override in harnesses.ADAPTERS and override != "command":
            # `task run --harness dsh` (an adapter NAME): every phase on that adapter, with the
            # toml's model only when the toml names the same harness
            hcfg = {**hcfg, "name": override, "types": {},
                    "command": harnesses.DEFAULT_COMMAND,
                    "model": hcfg.get("model", "") if hcfg.get("name") == override else ""}
            override = None
        if override is not None:                # `task run --harness CMD`: one command for all
            self.default = Harness(override, stdin=hcfg["stdin"], timeout_s=hcfg["timeout_s"],
                                   env=hcfg["env"], workspace=workspace, name="command")
            self.by_type: dict = {}
            return
        if cat is not None:
            harnesses.check_types(hcfg, cat)
        self.default = from_choice(harnesses.resolve(hcfg), hcfg, workspace, allow, jail)
        self.by_type = {t: from_choice(harnesses.resolve(hcfg, t), hcfg, workspace, allow, jail)
                        for t in (hcfg.get("types") or {})}

    def for_agent(self, agent: str) -> Harness:
        t = self.cat.type_of_agent(agent) if self.cat is not None else None
        return self.by_type.get(t, self.default)

    def check(self) -> None:
        for h in [self.default, *self.by_type.values()]:
            h.check()

    def run(self, prompt: str, *, agent: str, **kw) -> PhaseResult:
        return self.for_agent(agent).run(prompt, agent=agent, **kw)
