"""Session-wide guard: no `konstant board serve` a test started may outlive the test run.

Every fixture that starts a board stops it in a finalizer (also when its own setup fails), and this
autouse session fixture checks at the end of the run that no board process whose working directory
lies under this run's pytest basetemp is still alive. One that is still alive is killed and the run
FAILS, naming each process: a leaked board keeps a port and a deleted workspace open for hours (it
happened: wave L5-3's fixtures asserted between `board start` and their finalizer)."""
from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest


def board_processes(base: str) -> list:
    """(pid, cwd) of every `konstant board serve` process whose cwd is under `base` (a deleted
    cwd reads as `<path> (deleted)`)."""
    out = []
    base = os.path.realpath(base).rstrip("/") + "/"
    for d in Path("/proc").iterdir() if Path("/proc").is_dir() else []:
        if not d.name.isdigit() or int(d.name) == os.getpid():
            continue
        try:
            argv = (d / "cmdline").read_bytes().split(b"\0")
            cwd = os.readlink(d / "cwd")
        except OSError:
            continue
        words = [a.decode(errors="replace") for a in argv]
        if "konstant" not in " ".join(words) or "board" not in words or "serve" not in words:
            continue
        path = cwd[:-len(" (deleted)")] if cwd.endswith(" (deleted)") else cwd
        if (path.rstrip("/") + "/").startswith(base):
            out.append((int(d.name), cwd))
    return out


@pytest.fixture(scope="session", autouse=True)
def no_board_left_running(tmp_path_factory):
    base = str(tmp_path_factory.getbasetemp())
    yield
    left = board_processes(base)
    for pid, _cwd in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    if left:
        pytest.fail(f"{len(left)} `konstant board serve` process(es) a test started were still "
                    "running at the end of the session (killed now): "
                    + "; ".join(f"pid {p} cwd {c}" for p, c in left), pytrace=False)
