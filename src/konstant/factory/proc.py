"""The factory process on disk (docs/LEVEL5.md 6.1, 6.4): one factory per workspace.

  var/locks/factory.lock     an flock the running loop holds for its whole life: a second
                             `factory run|start` cannot take it and exits 2
  var/factory/factory.pid    the loop's pid; trusted only when that process is alive AND is a
                             `konstant factory run` of THIS workspace (REVIEW F-23: a stale pid
                             file and pid reuse never make `factory stop` signal another process)
  var/factory/STOP           the kill switch (`factory stop`): the loop starts nothing new, lets
                             its running steps finish (graceful drain) and exits; while it exists
                             no factory starts (`factory resume` clears it)
  var/factory/heartbeat.json written every tick: {pid, at, tick, state, steps, ready, progress_at,
                             tick_s}; older than three ticks = `stale` (status view, doctor)
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from pathlib import Path


def fdir(home) -> Path:
    return Path(home) / "var" / "factory"


def pid_file(home) -> Path:
    return fdir(home) / "factory.pid"


def stop_file(home) -> Path:
    return fdir(home) / "STOP"


def heartbeat_file(home) -> Path:
    return fdir(home) / "heartbeat.json"


def lock(home):
    """The factory's flock (an open file) or None when another factory holds it."""
    d = Path(home) / "var" / "locks"
    d.mkdir(parents=True, exist_ok=True)
    fh = open(d / "factory.lock", "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def is_factory(pid: int, home) -> bool:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
    except OSError:
        return False
    if not ("konstant" in " ".join(argv) and "factory" in argv and "run" in argv):
        return False
    try:                              # the loop runs in the workspace (it chdirs there)
        return os.path.realpath(os.readlink(f"/proc/{pid}/cwd")) == os.path.realpath(home)
    except OSError:
        return False


def running_pid(home) -> int | None:
    """The pid of this workspace's running factory loop, else None."""
    try:
        pid = int(pid_file(home).read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return None
    return pid if is_factory(pid, home) else None


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(data, sort_keys=True))
    tmp.replace(path)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def stopped_by(home) -> dict | None:
    """The kill switch's record ({by, at, reason}) when it is set."""
    p = stop_file(home)
    if not p.exists():
        return None
    return read_json(p) or {"at": "", "by": "", "reason": "STOP file present"}


def set_stop(home, by: str, reason: str) -> None:
    write_json(stop_file(home), {"by": by, "reason": reason,
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})


def state(home, tick_s: int) -> dict:
    """{state, pid, heartbeat, stop}: running | draining | stale | stopped."""
    pid = running_pid(home)
    hb = read_json(heartbeat_file(home))
    stop = stopped_by(home)
    if pid is None:
        st = "stopped"
    elif hb is None or time.time() - float(hb.get("ts", 0)) > 3 * max(1, int(tick_s)):
        st = "stale"
    elif stop or (hb or {}).get("state") == "draining":
        st = "draining"
    else:
        st = "running"
    return {"state": st, "pid": pid, "heartbeat": hb, "stop": stop}


class Step:
    """One konstant verb the loop runs as a child process (its output in var/factory/steps/)."""

    def __init__(self, action, argv: list, log: Path, env: dict, cwd: Path):
        self.action, self.log, self.started = action, log, time.time()
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fh = open(log, "ab")
        self.proc = subprocess.Popen(argv, stdout=self.fh, stderr=subprocess.STDOUT, env=env,
                                     cwd=str(cwd), stdin=subprocess.DEVNULL)

    def poll(self):
        rc = self.proc.poll()
        if rc is not None and not self.fh.closed:
            self.fh.close()
        return rc

    def tail(self, n: int = 3) -> list:
        try:
            lines = self.log.read_text(errors="replace").splitlines()
        except OSError:
            return []
        return [ln for ln in lines if ln.strip()][-n:]

    def info(self) -> dict:
        a = self.action
        return {"kind": a.kind, "goal": a.goal, "job": a.job, "pid": self.proc.pid,
                "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.started)),
                "log": str(self.log)}
