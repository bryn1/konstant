"""The factory's events and the notifier (docs/LEVEL5.md 6.3, 4.0 step 3).

Every event is one JSON line in var/factory/events.jsonl (machinery: no phase writes it):
{id, event, kind (escalation|outcome), goal, job, display_id, reason, at, board_url}. The reason is
one redacted line (board/redact.py) and never carries a brief, a scenario or a token.

Only ESCALATIONS are delivered, to [notify] kind:
  stdout   a `konstant notify: ...` line on the factory process's stderr
  file     one `EVENT goal job N: reason` line in var/factory/notify.log
  webhook  POST of the payload {event, goal, job, display_id, reason, at, board_url} (nothing
           else: no brief, acceptance or evidence) to [notify] url: https, or http to a loopback
           host listed in [notify] url_hosts; [notify] retries more tries
  chat     into the orchestrator session the goal came from: var/factory/chat/inbox/<session>.jsonl
           (a goal filed from a file, or an event of no goal: the `_workspace` inbox every session
           reads); `konstant chat turn`, which the konstant-gate dsh plugin runs on the owner's
           next message, shows it there (factory/chat.py)
Outcomes (FILED, SHIPPED, ROLLED_BACK, GOAL_DONE) are never pushed: the status view and the events
file hold them.

One notification per (goal, job, event) until the owner acknowledges it: the board keeps the open
escalation (`escalations`, one open row per key) and a repeat is recorded as `suppressed`, not
delivered. A delivery that fails after the retries is SPOOLED (var/factory/spool/<id>.json) and
never silently dropped; the factory loop halts while the spool is not empty (`notifier failed:
factory halted`), so the factory never keeps working while the owner cannot be reached.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ESCALATIONS = ("BLOCKED", "DECISION", "BUDGET_STOP", "LEAK", "ROLLBACK_FAILED", "HALTED")
OUTCOMES = ("FILED", "SHIPPED", "ROLLED_BACK", "GOAL_DONE")
KINDS = ("stdout", "file", "webhook", "chat")
PAYLOAD = ("event", "goal", "job", "display_id", "reason", "at", "board_url")
WORKSPACE_INBOX = "_workspace"
_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class NotifyError(Exception):
    """The notifier could not deliver (after its retries)."""


def factory_dir(home) -> Path:
    d = Path(home) / "var" / "factory"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)
    return d


def events_path(home) -> Path:
    return Path(home) / "var" / "factory" / "events.jsonl"


def _lines(path: Path) -> list:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def read_events(home) -> list:
    return _lines(events_path(home))


def _append(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(text)


def check_url(url: str, hosts) -> str | None:
    """Why a webhook URL is refused (None: fine): https, or http to a listed loopback host."""
    from konstant.config import is_loopback
    p = urllib.parse.urlsplit(url or "")
    if p.scheme == "https" and p.hostname:
        return None
    if p.scheme == "http" and p.hostname and p.hostname in hosts and is_loopback(p.hostname):
        return None
    return (f"webhook URL {url!r} refused: https, or http to a loopback host listed in [notify] "
            "url_hosts")


def payload(rec: dict) -> dict:
    return {k: rec.get(k) for k in PAYLOAD}


def text_of(rec: dict) -> str:
    job = f" job {rec.get('display_id') or rec.get('job')}" if rec.get("job") else ""
    return f"{rec['event']} {rec.get('goal') or '-'}{job}: {rec.get('reason', '')}"


def inbox_path(home, session: str) -> Path:
    return Path(home) / "var" / "factory" / "chat" / "inbox" / f"{session}.jsonl"


def read_inbox(home, session: str) -> list:
    return _lines(inbox_path(home, session))


def _webhook(cfg, rec: dict, url: str) -> str:
    n = cfg.data["notify"]
    why = check_url(url, n["url_hosts"])
    if why:
        raise NotifyError(why)
    data = json.dumps(payload(rec), sort_keys=True).encode("utf-8")
    last = ""
    for i in range(1 + max(0, int(n["retries"]))):
        if i:
            time.sleep(float(n["retry_s"]))
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=float(n["timeout_s"])) as resp:
                if 200 <= resp.status < 300:
                    return f"webhook {urllib.parse.urlsplit(url).hostname}"
                last = f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError) as exc:
            last = str(getattr(exc, "reason", exc))[:200]
    raise NotifyError(f"webhook {urllib.parse.urlsplit(url).hostname} did not take the event "
                      f"after {1 + int(n['retries'])} tries ({last})")


def deliver(cfg, rec: dict, kind: str = "", url: str = "") -> str:
    """Deliver one escalation by `kind` (default [notify] kind); -> where it went."""
    kind = kind or cfg.data["notify"]["kind"]
    d = factory_dir(cfg.home)
    try:
        if kind == "stdout":
            print(f"konstant notify: {text_of(rec)}", file=sys.stderr, flush=True)
            return "stdout"
        if kind == "file":
            _append(d / "notify.log", text_of(rec) + "\n")
            return "file"
        if kind == "webhook":
            return _webhook(cfg, rec, url or cfg.data["notify"]["url"])
        if kind == "chat":
            session = rec.get("session") or WORKSPACE_INBOX
            if not _SESSION.fullmatch(session):
                raise NotifyError(f"chat session {session!r} is not a session id")
            p = inbox_path(cfg.home, session)
            for x in (p.parent.parent, p.parent):
                x.mkdir(parents=True, exist_ok=True, mode=0o700)
            _append(p, json.dumps(rec, sort_keys=True) + "\n")
            return f"chat {session}"
    except OSError as exc:
        raise NotifyError(f"{kind}: {exc.strerror or exc}") from None
    raise NotifyError(f"[notify] kind {kind!r} is not one of {', '.join(KINDS)}")


def spool_dir(home) -> Path:
    return Path(home) / "var" / "factory" / "spool"


def spooled(home) -> list:
    d = spool_dir(home)
    out = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            out.append({**json.loads(f.read_text()), "_file": str(f)})
        except (OSError, ValueError):
            out.append({"_file": str(f), "event": "?", "reason": "unreadable spool file"})
    return out


def _spool(cfg, rec: dict, why: str) -> None:
    d = spool_dir(cfg.home)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(d / f"{int(rec['id']):08d}.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps({**rec, "undelivered": why}, sort_keys=True))


def local(cfg, text: str) -> None:
    """A halt is always told on stderr and in notify.log, whatever [notify] kind (6.3)."""
    print(f"konstant notify: {text}", file=sys.stderr, flush=True)
    try:
        _append(factory_dir(cfg.home) / "notify.log", text + "\n")
    except OSError:
        pass


def factory_client(cfg):
    from konstant.client import Client, ClientError, token_for
    try:
        return Client(cfg.base_url, token_for(cfg, "factory"), timeout=10)
    except (ClientError, OSError):
        return None


def _register(client, rec: dict) -> tuple:
    """(escalation id, new?) from the board; (None, True) when the board cannot be asked (the
    escalation is then delivered anyway: dedupe never costs a notification)."""
    if client is None:
        return None, True
    try:
        r = client.post("/api/factory/escalations", {
            "goal": rec.get("goal") or "", "job": rec.get("job"), "kind": rec["event"],
            "reason": rec["reason"], "event_id": rec["id"]})
        return r["id"], bool(r["new"])
    except Exception:  # noqa: BLE001 - the board is down or refused: deliver, never drop
        return None, True


def _session_of(client, goal: str) -> str:
    if client is None or not goal:
        return ""
    try:
        return client.get(f"/api/goals/{goal}").get("session") or ""
    except Exception:  # noqa: BLE001 - unknown session: the workspace inbox
        return ""


def emit(cfg, event: str, goal: str = "", job=None, display_id: str = "",
         reason: str = "", client=None) -> dict:
    """Record one event and deliver it when it is a new escalation. Never raises on a failed
    delivery (the event is spooled; the loop halts on a non-empty spool). Returns the record."""
    from konstant.board.redact import redact
    if event not in ESCALATIONS + OUTCOMES:
        raise ValueError(f"unknown factory event {event!r}")
    d = factory_dir(cfg.home)
    line = " ".join(redact(str(reason or "")).split())[:500]
    esc = event in ESCALATIONS
    if esc and client is None:
        client = factory_client(cfg)
    with open(d / "events.lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        rec = {"id": len(read_events(cfg.home)) + 1, "event": event,
               "kind": "escalation" if esc else "outcome", "goal": goal or None,
               "job": job, "display_id": display_id or None, "reason": line,
               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "board_url": cfg.base_url}
        if esc:
            rec["escalation"], new = _register(client, rec)
            if not new:
                rec["suppressed"] = True          # open and unacknowledged: told once
        _append(d / "events.jsonl", json.dumps(rec, sort_keys=True) + "\n")
    if not esc or rec.get("suppressed"):
        return rec
    if cfg.data["notify"]["kind"] == "chat":
        rec["session"] = _session_of(client, goal)
    try:
        where = deliver(cfg, rec)
    except NotifyError as exc:
        _spool(cfg, rec, str(exc))
        local(cfg, f"undelivered {text_of(rec)} ({exc}): spooled; the factory halts")
        rec["undelivered"] = str(exc)
        return rec
    rec["delivered"] = where
    if client is not None and rec.get("escalation"):
        try:
            client.post(f"/api/factory/escalations/{rec['escalation']}/delivered", {"to": where})
        except Exception:  # noqa: BLE001 - delivered is what matters; the mark is bookkeeping
            pass
    return rec


def redeliver(cfg, client=None) -> list:
    """Try every spooled event again; -> the ones still undelivered (removed when delivered)."""
    left = []
    client = client or factory_client(cfg)
    for rec in spooled(cfg.home):
        f = rec.pop("_file")
        rec.pop("undelivered", None)
        try:
            where = deliver(cfg, rec)
        except NotifyError as exc:
            left.append({**rec, "undelivered": str(exc)})
            continue
        Path(f).unlink(missing_ok=True)
        if client is not None and rec.get("escalation"):
            try:
                client.post(f"/api/factory/escalations/{rec['escalation']}/delivered",
                            {"to": where})
            except Exception:  # noqa: BLE001 - bookkeeping only
                pass
    return left
