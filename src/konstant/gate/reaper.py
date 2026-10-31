"""Nothing a phase starts outlives the phase (REVIEW F-05).

`konstant task run` makes itself a child subreaper (Linux prctl PR_SET_CHILD_SUBREAPER): a
process a phase detaches (setsid, double fork, a cleaned environment) is re-parented to the runner
instead of init, so it stays a DESCENDANT the runner can find. After every phase group the runner
SIGKILLs every live descendant and reaps the zombies, before it snapshots OUT and before the next
phase starts. A process that escapes through another service (cron, systemd-run, ssh to localhost)
is out of reach: those commands are not on a phase's allow list. Not Linux: a no-op (documented).
"""
from __future__ import annotations

import ctypes
import os
import signal
import sys
import time

PR_SET_CHILD_SUBREAPER = 36


def become_subreaper() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


def _table() -> dict:
    """{ppid: [(pid, state)]} from /proc."""
    out: dict = {}
    for d in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat", encoding="utf-8", errors="replace") as fh:
                rest = fh.read().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        out.setdefault(int(rest[1]), []).append((int(d), rest[0]))
    return out


def live_descendants(pid: int | None = None) -> list:
    table, out, stack = _table(), [], [pid or os.getpid()]
    while stack:
        for child, state in table.get(stack.pop(), []):
            stack.append(child)
            if state != "Z":
                out.append(child)
    return out


def _reap_zombies() -> None:
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def kill_leftovers(rounds: int = 5) -> int:
    """SIGKILL every live descendant of this process; returns how many were found."""
    seen: set = set()
    for _ in range(rounds):
        pids = live_descendants()
        if not pids:
            break
        for p in pids:
            seen.add(p)
            try:
                os.kill(p, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(0.05)
        _reap_zombies()
    _reap_zombies()
    return len(seen)
