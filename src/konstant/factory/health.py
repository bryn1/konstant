"""The factory's health (docs/LEVEL5.md 6.4): the heartbeat and the stall check.

  heartbeat   var/factory/heartbeat.json every tick (factory/proc.py reads it: older than three
              ticks = stale, on the status view and in `doctor`)
  stall       progress = a change of the board (ships, goals, job states) or new output of a
              running step (its log, the phase files of its run); none for [factory]
              stall_after_s while work is ready or running -> one BLOCKED escalation
              (`factory stalled: ...`), told once until acknowledged like every escalation
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from konstant.client import ClientError
from konstant.factory import notify, proc


def activity(f) -> float:
    newest = 0.0
    for st in f.running:
        for p in [st.log, *run_files(f, st.started)]:
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                pass
    return newest


def run_files(f, since: float) -> list:
    runs = f.home / "var" / "runs"
    out = []
    for d in runs.iterdir() if runs.is_dir() else []:
        try:
            if d.stat().st_mtime >= since - 1:
                out += [d, *(d / "phases").glob("*")]
        except OSError:
            pass
    return out


def check_stall(f, p_fp: str) -> None:
    now = time.time()
    fp = hashlib.sha256((p_fp + str(activity(f))).encode()).hexdigest()
    if fp != f.fp:
        f.fp, f.progress_at = fp, now
        return
    if (f.ready or f.running) and now - f.progress_at >= f.stall_s:
        notify.emit(f.cfg, "BLOCKED", reason=f"factory stalled: no progress for "
                    f"{int(now - f.progress_at)}s while {f.ready} action(s) are ready "
                    f"and {len(f.running)} step(s) run", client=f.factory)
        f.progress_at = now


def fingerprint(f) -> str:
    try:
        ships = f.viewer.get("/api/ships")["ships"]
        goals = f.viewer.get("/api/goals")["goals"]
        jobs = f.viewer.get("/api/jobs", limit=10000)["jobs"]
    except ClientError:
        return ""
    return json.dumps([[(s["id"], s["state"]) for s in ships],
                       [(g["slug"], g["status"], g["intake"]) for g in goals],
                       [(j["id"], j["status"], j.get("verify_round")) for j in jobs]])


def heartbeat(f, state: str) -> None:
    now = time.time()
    proc.write_json(proc.heartbeat_file(f.home), {
        "pid": os.getpid(), "ts": now, "tick": f.ticks, "state": state,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "steps": [s.info() for s in f.running], "ready": f.ready,
        "progress_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f.progress_at)),
        "tick_s": f.tick_s, "goals": f.states})


def unreachable(exc) -> bool:
    """A board that cannot be reached at all (no HTTP answer), not a refusal."""
    return isinstance(exc, ClientError) and not getattr(exc, "status", 0)


def board_down(f, exc, sleep=time.sleep) -> None:
    """The board does not answer (REVIEW L5-R2 K-13): wait one tick and try again; once it has
    been down for [factory] down_after_s, tell the owner ONCE per outage through the channels
    that need no board (notify.factory_down: stderr, notify.log, [notify] mirror)."""
    now = time.time()
    if not getattr(f, "down_since", 0):
        f.down_since, f.down_told = now, False
        f.log(f"konstant factory: the board does not answer ({getattr(exc, 'message', exc)}); "
              "waiting for it")
    after = int(f.cfg.data["factory"]["down_after_s"])
    if not f.down_told and now - f.down_since >= after:
        notify.factory_down(f.cfg, int((now - f.down_since) // 60),
                            str(getattr(exc, "message", exc)))
        f.down_told = True
    heartbeat(f, "waiting-for-board")
    sleep(f.tick_s)


def board_back(f) -> None:
    if getattr(f, "down_since", 0):
        f.log(f"konstant factory: the board answers again after "
              f"{int(time.time() - f.down_since)}s")
        f.down_since, f.down_told = 0, False
