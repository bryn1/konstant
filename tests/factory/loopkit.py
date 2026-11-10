"""The factory-loop test harness (docs/LEVEL5.md 6.6, wave L5-5): the ship workspace of
tests/ship/conftest.py (board running, project `greeter` = the TARGET on branch main, every phase
through the real dsh adapter with the stub dsh + the fake harness, offline), [notify] kind = file,
[factory] tick_s = 1, plus a goal filed by the owner. `factory run` is driven as a subprocess,
exactly as the owner (or the systemd unit) runs it."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from tests.ship.conftest import make_ship_ws

GOAL = """[goal]
id = "greeter"
project = "greeter"
text = \"\"\"
A small greeting library: greet(name) and a CLI `greet NAME`.
\"\"\"
[limits]
max_attempts = 3
{extra}
"""
def goal_text(limits: str = "") -> str:
    """The goal file; `limits` lines join [limits] (a max_attempts there replaces the 3)."""
    text = GOAL.format(extra=limits)
    return text.replace("max_attempts = 3\n", "", 1) if "max_attempts" in limits else text


FAST = '[gate]\nmax_cycles = 1\nmax_resumes = 0\n'


def make_lws(tmp: Path, notify: str = 'kind = "file"', factory: str = "", limits: str = "",
             tail: str = "", goal: bool = True, harness: str = ""):
    s = make_ship_ws(tmp, tail=f'[notify]\n{notify}\n[factory]\ntick_s = 1\n{factory}\n' + FAST
                     + tail)
    if harness:                     # replace the workspace's [harness] (dsh) with this one
        cfg = s.w.home / "konstant.toml"
        s.w.stop_board()
        cfg.write_text(cfg.read_text().replace('[harness]\nname = "dsh"\n', harness, 1))
        s.w.ok("board", "start")
    if goal:
        (s.w.src / "goal.toml").write_text(goal_text(limits))
        r = s.w.run("--as", "owner", "goal", "add", s.w.src / "goal.toml")
        assert r.returncode == 0, r.stderr
    return s


def env(s, mode: str = "", **extra) -> dict:
    e = s.w.henv(**({"FAKE_HARNESS_MODE": mode} if mode else {}), **extra)
    return e


def factory(s, *args, mode: str = "", timeout: int = 1800, **extra) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "konstant", "factory", *map(str, args)],
                          capture_output=True, text=True, env=env(s, mode, **extra),
                          cwd=str(s.w.home), timeout=timeout, stdin=subprocess.DEVNULL)


def start_bg(s, *args, mode: str = "", **extra) -> subprocess.Popen:
    """`factory run ARGS` in the background, in its own process group (like `factory start`)."""
    log = open(s.w.src / f"factory-{time.time_ns()}.log", "wb")
    return subprocess.Popen([sys.executable, "-m", "konstant", "factory", "run", *map(str, args)],
                            stdout=log, stderr=subprocess.STDOUT, env=env(s, mode, **extra),
                            cwd=str(s.w.home), stdin=subprocess.DEVNULL, start_new_session=True)


def kill_group(p: subprocess.Popen, sig=signal.SIGKILL) -> None:
    try:
        os.killpg(p.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def wait_for(pred, timeout: float = 300, every: float = 0.5):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(every)
    return None


def notify_lines(s) -> list:
    p = s.w.home / "var" / "factory" / "notify.log"
    return p.read_text().splitlines() if p.is_file() else []


def events(s) -> list:
    p = s.w.home / "var" / "factory" / "events.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []


def goal(s, slug: str = "greeter") -> dict:
    return s.w.json("goal", "show", slug)


def jobs(s) -> list:
    return s.w.json("job", "list", "--project", "greeter")


def diagnose(s) -> str:
    """What a stuck factory test needs in its failure message (the CI runner keeps nothing
    else): the goal, each job's status, the last events and the tail of the factory's log."""
    out = []
    try:
        g = goal(s)
        out.append(f"goal: status {g.get('status')} intake {g.get('intake')}")
    except Exception as exc:                         # noqa: BLE001 - diagnostics only
        out.append(f"goal: unreadable ({exc})")
    try:
        out += [f"job {j['display_id']}: {j['status']}" for j in jobs(s)]
    except Exception as exc:                         # noqa: BLE001
        out.append(f"jobs: unreadable ({exc})")
    out += [json.dumps(e)[:400] for e in events(s)[-8:]]
    for log in sorted(s.w.src.glob("factory-*.log"))[-1:]:
        out += ["--- " + log.name] + log.read_text(errors="replace").splitlines()[-40:]
    return "\n".join(out)

