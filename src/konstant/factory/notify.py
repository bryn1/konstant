"""The factory's events and the notifier, as far as intake needs them (docs/LEVEL5.md 6.3, 4.0
step 3; the full notifier - webhook, retries, the halt on a failed delivery, acks - is wave L5-5).

Every event is one JSON line in var/factory/events.jsonl (machinery: no phase writes it):
{id, event, kind (escalation|outcome), goal, job, display_id, reason, at, board_url}. The reason is
one redacted line (board/redact.py) and never carries a brief, a scenario or a token.
Escalations (BLOCKED, DECISION, BUDGET_STOP, LEAK, ROLLBACK_FAILED, HALTED) also go to
[notify] kind: `stdout` (stderr of the factory process), `file` (var/factory/notify.log, one
`EVENT goal ...` line each) or `chat` (nothing more here: the konstant-gate plugin shows them in
the owner's session at his next turn, `konstant chat turn`). Outcomes (FILED, SHIPPED, ...) are
never pushed: they are read on request.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ESCALATIONS = ("BLOCKED", "DECISION", "BUDGET_STOP", "LEAK", "ROLLBACK_FAILED", "HALTED")
OUTCOMES = ("FILED", "SHIPPED", "ROLLED_BACK", "GOAL_DONE")


def factory_dir(home) -> Path:
    d = Path(home) / "var" / "factory"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)
    return d


def events_path(home) -> Path:
    return Path(home) / "var" / "factory" / "events.jsonl"


def read_events(home) -> list:
    try:
        lines = events_path(home).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _append(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(text)


def emit(cfg, event: str, goal: str = "", job=None, display_id: str = "",
         reason: str = "") -> dict:
    """Record one event (and deliver it when it is an escalation). Returns the record."""
    from konstant.board.redact import redact
    if event not in ESCALATIONS + OUTCOMES:
        raise ValueError(f"unknown factory event {event!r}")
    d = factory_dir(cfg.home)
    line = " ".join(redact(str(reason or "")).split())[:500]
    rec = {"id": len(read_events(cfg.home)) + 1, "event": event,
           "kind": "escalation" if event in ESCALATIONS else "outcome", "goal": goal or None,
           "job": job, "display_id": display_id or None, "reason": line,
           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "board_url": cfg.base_url}
    _append(d / "events.jsonl", json.dumps(rec, sort_keys=True) + "\n")
    if rec["kind"] == "escalation":
        kind = cfg.data["notify"]["kind"]
        text = f"{event} {goal or '-'}{' job ' + str(display_id or job) if job else ''}: {line}"
        if kind == "file":
            _append(d / "notify.log", text + "\n")
        elif kind == "stdout":
            print(f"konstant notify: {text}", file=sys.stderr, flush=True)
    return rec
