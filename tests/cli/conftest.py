"""CLI harness: a temp workspace, a free loopback port, a real board started by `board start`.

Every command runs as a subprocess (`python -m konstant ...`) with KONSTANT_HOME set, exactly as
a user or an agent would run it. The board is stopped at teardown.
"""
from __future__ import annotations

import os
import site
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# this interpreter's user site-packages ("" when disabled) and the HOME it hangs under: where a
# source checkout keeps konstant's own deps when nothing else does (tomli on Python 3.10)
USER_SITE = site.getusersitepackages() if site.ENABLE_USER_SITE else ""
USER_HOME = str(Path(USER_SITE).parents[3]) if USER_SITE else ""


def fix_pythonpath(env: dict) -> dict:
    """Make what THIS interpreter can import also importable in a test subprocess.

    Two harness-wide faults the copied environment carries: (1) the documented `PYTHONPATH=src`
    is relative to the pytest invocation dir, and every test subprocess runs with cwd = a temp
    workspace, where it resolves to nothing (`No module named konstant`) — each entry is
    resolved against REPO, the dir that invocation runs from; (2) a test that redirects HOME
    (a phase's fake home, tests/factory/conftest.py) hides this interpreter's user
    site-packages, where a source checkout keeps konstant's own deps — an install keeps them
    HOME-independent, so under a redirected HOME the dir is put on the path. A minimal env that
    does not name PYTHONPATH inherits the caller's (8074df3: a child running `-m
    konstant`/`-m pytest` needs this run's import path, e.g. knut's sealed re-run); REPO's own
    src is always the first entry, so a child imports konstant exactly as the parent does (the
    bare run, PYTHONPATH unset) and the documented `src` entry dedupes to one. The one
    place this is done; env() below and the hand-built subprocess envs
    (tests/holdout/test_author_reliability.py, tests/factory/test_examples.py) call it here."""
    raw = env.get("PYTHONPATH", os.environ.get("PYTHONPATH", ""))
    entries = [str(REPO / "src")] + [p for p in raw.split(os.pathsep) if p]
    entries = [str(REPO / p) if not Path(p).is_absolute() else p for p in entries]
    if USER_SITE and env.get("HOME", USER_HOME) != USER_HOME and os.path.isdir(USER_SITE):
        entries.append(USER_SITE)
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(entries))
    return env


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Workspace:
    def __init__(self, home: Path):
        self.home = home
        (home / "konstant.toml").write_text(f"[board]\nport = {free_port()}\n")

    def env(self, **extra) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("KONSTANT_")}
        # KONSTANT_ENV_PASSTHROUGH names the test-harness control vars (FAKE_*/STUB_*/PROBE_*) a
        # closed phase's env allowlist keeps (tests/conftest.py; REVIEW L5-R1 H-05): it is
        # konstant config, not a per-workspace var, so it survives the KONSTANT_ strip here.
        passthrough = os.environ.get("KONSTANT_ENV_PASSTHROUGH")
        if passthrough:
            env["KONSTANT_ENV_PASSTHROUGH"] = passthrough
        env.update(KONSTANT_HOME=str(self.home), **extra)
        return fix_pythonpath(env)

    def stop_board(self) -> None:
        """`board stop`, and when that cannot run (a test broke konstant.toml, the CLI refuses)
        the board this workspace's var/board.pid names is killed: a fixture never leaves one
        running (tests/conftest.py fails the session if it does)."""
        self.run("board", "stop")
        pidfile = self.home / "var" / "board.pid"
        try:
            pid = int(pidfile.read_text().split()[0])
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except (OSError, ValueError, IndexError):
            return
        if b"board" in cmd and b"serve" in cmd:
            import signal
            import time
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                if not Path(f"/proc/{pid}").exists():
                    break
                time.sleep(0.1)
            else:
                os.kill(pid, signal.SIGKILL)

    def run(self, *args, env=None, stdin=None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "konstant", *map(str, args)],
                              capture_output=True, text=True, env=env or self.env(),
                              input=stdin, timeout=60, cwd=str(self.home))

    def ok(self, *args, **kw) -> subprocess.CompletedProcess:
        res = self.run(*args, **kw)
        assert res.returncode == 0, f"{args}: rc={res.returncode}\n{res.stdout}\n{res.stderr}"
        return res

    def write(self, name: str, text: str) -> Path:
        p = self.home / name
        p.write_text(text)
        return p


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    w = Workspace(tmp_path_factory.mktemp("ws"))
    w.ok("board", "init")
    w.ok("board", "start")
    try:
        w.ok("project", "add", "demo")
        yield w
    finally:
        w.stop_board()


@pytest.fixture()
def fresh(tmp_path):
    """A workspace that is NOT initialised and has no board."""
    return Workspace(tmp_path)
