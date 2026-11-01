"""CLI harness: a temp workspace, a free loopback port, a real board started by `board start`.

Every command runs as a subprocess (`python -m konstant ...`) with KONSTANT_HOME set, exactly as
a user or an agent would run it. The board is stopped at teardown.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


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
        env.update(KONSTANT_HOME=str(self.home), **extra)
        return env

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
