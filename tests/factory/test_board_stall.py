"""The factory loop and a board that stops answering for a while (wave L5-L, the live run's halt).

Live: ONE board request of the `--until-idle` factory timed out (30 s, the host busy) four and a
half hours into the run; the loop treated it as an internal error, halted (exit 5) and left its
running intake behind, still calling the board. Now `--until-idle` and `--once` wait an
unreachable board out for at most `[factory] down_after_s` (as the forever loop does, K-13, but
bounded), and an internal error stops the steps the factory started (a ship is never cut).
"""
from __future__ import annotations

import sys

import pytest

from konstant import config
from konstant.client import ClientError
from konstant.factory import health, loop, proc
from konstant.factory.steps import Action

EXIT_ERROR = 5


def make(tmp_path, down_after=600, mode="until_idle"):
    (tmp_path / "konstant.toml").write_text(f"[factory]\ntick_s = 1\ndown_after_s = {down_after}\n")
    (tmp_path / "var" / "factory").mkdir(parents=True)
    f = Fake(config.load(tmp_path), mode=mode, log=lambda m: None)
    return f


class Fake(loop.Factory):
    """The loop with its board calls replaced: `script` = what each tick does."""
    script: list = []
    halted: list = []

    def tick(self):
        what = self.script.pop(0) if self.script else 0
        if isinstance(what, Exception):
            raise what
        return what

    def halt(self, reason):
        self.halted.append(reason)

    def reap(self):
        return 0


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(health, "heartbeat", lambda f, s: None)
    monkeypatch.setattr(health, "check_stall", lambda f, fp: None)
    monkeypatch.setattr(health, "fingerprint", lambda f: "")
    monkeypatch.setattr(health.board_down, "__defaults__", (lambda s: None,))
    monkeypatch.setattr(loop.notify, "emit", lambda *a, **k: None)
    monkeypatch.setattr(loop.notify, "factory_down", lambda *a, **k: None)


def unreachable():
    return ClientError("board unreachable at http://127.0.0.1:1 (timed out)")


def test_until_idle_waits_out_a_board_timeout_red(tmp_path):
    """The live shape: one request times out, the board answers again, the run goes on."""
    f = make(tmp_path)
    f.script, f.halted = [unreachable(), unreachable(), 0], []
    assert f.run() != EXIT_ERROR and f.halted == [], f.halted
    assert health.down_for(f) == 0                          # told that the board is back


def test_until_idle_still_halts_a_board_down_too_long_green(tmp_path, monkeypatch):
    """The bound: down for [factory] down_after_s -> the internal error, HALTED, exit 5."""
    f = make(tmp_path, down_after=10)
    clock = [1000.0]
    monkeypatch.setattr(health.time, "time", lambda: clock[0])
    monkeypatch.setattr(health.board_down, "__defaults__",
                        (lambda s: clock.__setitem__(0, clock[0] + 6),))
    f.script, f.halted = [unreachable()] * 10, []
    assert f.run() == EXIT_ERROR and len(f.halted) == 1, f.halted
    assert "board unreachable" in f.halted[0]


def test_a_refusal_is_never_waited_out_green(tmp_path):
    f = make(tmp_path)
    f.script, f.halted = [ClientError("refused: 403", status=403)], []
    assert f.run() == EXIT_ERROR and f.halted


def test_an_internal_error_stops_the_steps_it_started_red(tmp_path):
    """Live: the halted factory exited 5 and its intake ran on. A ship is never cut."""
    f = make(tmp_path)
    work = Action(kind="intake", goal="g")
    ship = Action(kind="ship", goal="g", job=2)
    sleeper = [sys.executable, "-c", "import time; time.sleep(600)"]
    quick = [sys.executable, "-c", "import time; time.sleep(1)"]
    a = proc.Step(work, sleeper, tmp_path / "a.log", {}, tmp_path)
    b = proc.Step(ship, quick, tmp_path / "b.log", {}, tmp_path)
    f.running = [a, b]
    f.script, f.halted = [RuntimeError("a state the factory does not understand")], []
    try:
        assert f.run() == EXIT_ERROR and f.halted
        assert a.proc.poll() is not None, "the intake outlived the halted factory"
        assert b.proc.poll() == 0                                # the ship ran to its end
    finally:
        for st in (a, b):
            if st.proc.poll() is None:
                st.proc.kill()
                st.proc.wait()


def test_stop_steps_kills_a_step_that_ignores_sigterm(tmp_path):
    ready = tmp_path / "ready"
    stubborn = [sys.executable, "-c", "import pathlib, signal, sys, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "pathlib.Path(sys.argv[1]).write_text('x'); time.sleep(600)", str(ready)]
    st = proc.Step(Action(kind="attempt", goal="g", job=3), stubborn, tmp_path / "s.log", {},
                   tmp_path)
    try:
        while not ready.exists() and st.proc.poll() is None:
            pass
        proc.stop_steps([st], grace=1.0)
        assert st.proc.returncode == -9          # SIGTERM ignored, then SIGKILL
    finally:
        if st.proc.poll() is None:
            st.proc.kill()
            st.proc.wait()
