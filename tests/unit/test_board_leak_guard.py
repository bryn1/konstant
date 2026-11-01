"""The session guard of tests/conftest.py finds a `konstant board serve` process left running in
this run's basetemp (a deleted workspace too), and ignores one outside it."""
from __future__ import annotations

import shutil
import subprocess
import sys
import time

from tests.conftest import board_processes

FAKE_BOARD = [sys.executable, "-c", "import time; time.sleep(60)", "-m", "konstant", "board",
              "serve"]


def _spawn(cwd):
    p = subprocess.Popen(FAKE_BOARD, cwd=str(cwd), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    time.sleep(0.2)
    return p


def test_guard_finds_a_board_left_in_basetemp_red_then_gone_green(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    p = _spawn(ws)
    try:
        assert p.pid in [pid for pid, _c in board_processes(str(tmp_path))]
        shutil.rmtree(ws)                                  # a deleted workspace still counts
        found = dict(board_processes(str(tmp_path)))
        assert found.get(p.pid, "").endswith("(deleted)")
    finally:
        p.kill()
        p.wait()
    assert p.pid not in [pid for pid, _c in board_processes(str(tmp_path))]


def test_guard_ignores_a_board_outside_basetemp(tmp_path, tmp_path_factory):
    other = tmp_path_factory.mktemp("elsewhere")
    p = _spawn(other)
    try:
        assert p.pid not in [pid for pid, _c in board_processes(str(tmp_path))]
    finally:
        p.kill()
        p.wait()
