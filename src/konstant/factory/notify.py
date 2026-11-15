"""The factory's events and the notifier (docs/LEVEL5.md 6.3, 4.0 step 3).
reason: the one place an event is recorded and delivered (every channel, the mirror, the spool,
`notify test` and doctor's self-test); split, the delivery rules would live in two places.

Every event is one JSON line in var/factory/events.jsonl (machinery: no phase writes it):
{id, event, kind (escalation|outcome), goal, job, display_id, reason, at, board_url}. The reason is
one redacted line (board/redact.py) and never carries a brief, a scenario or a token.

Only ESCALATIONS are delivered, to [notify] kind:
  stdout   a `konstant notify: ...` line on the factory process's stderr
  file     one `EVENT goal job N: reason` line in var/factory/notify.log
  webhook  POST of the payload {event, goal, job, display_id, reason, at, board_url} (nothing
           else: no brief, acceptance or evidence) to [notify] url: https, or http to a loopback
           host listed in [notify] url_hosts; [notify] retries more tries
  chat     into the ONE owner inbox var/factory/chat/owner.jsonl (REVIEW L5-R2 K-05/K-08): no
           inbox name is derived from a session id, so no event can miss its inbox. EVERY session
           started with `konstant dsh` shows it at its next turn (`konstant chat turn`, run by the
           konstant-gate plugin on the owner's genuine message; factory/chat.py), the session the
           goal came from included; a session that starts later shows every escalation still
           open. The board's `delivered_at` is set when an owner turn SHOWED it, not by the append
Escalations also go to the optional second channel `[notify] mirror` ("file" or "webhook", url
`[notify] mirror_url`): a mirror that cannot deliver is told on stderr and in notify.log; only the
primary channel's failure halts. Outcomes (FILED, SHIPPED, GOAL_DONE) are never pushed: the status
view and the events file hold them. ROLLED_BACK is an escalation since L5-F2b (K-17): the owner
hears of every rollback.

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

ESCALATIONS = ("BLOCKED", "DECISION", "BUDGET_STOP", "LEAK", "ROLLBACK_FAILED", "HALTED",
               "ROLLED_BACK")
OUTCOMES = ("FILED", "SHIPPED", "GOAL_DONE")
TEST = "TEST"                       # `notify test`: an event of kind "test", never an escalation
KINDS = ("stdout", "file", "webhook", "chat")
MIRROR_KINDS = ("", "file", "webhook")
PAYLOAD = ("event", "goal", "job", "display_id", "reason", "at", "board_url")
OWNER_INBOX = "owner.jsonl"
# THE one session-id scheme (REVIEW L5-R2 K-05): every writer (goal add --from-chat, an owner
# action, a chat cursor) and every reader (chat turn) validates with session_id()
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def session_id(session) -> str:
    """The session id, validated; ValueError otherwise (one scheme, checked at write and read)."""
    s = str(session or "").strip()
    if not SESSION.fullmatch(s):
        raise ValueError(f"chat session {session!r} is not a session id (letters, digits, '.', "
                         "'_', ':', '-'; up to 128 characters, starting with a letter or digit)")
    return s


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


def inbox_path(home, session: str = "") -> Path:
    """The ONE owner inbox (every session reads it; `session` is accepted and ignored)."""
    return Path(home) / "var" / "factory" / "chat" / OWNER_INBOX


def read_inbox(home, session: str = "") -> list:
    return _lines(inbox_path(home))


def inbox_since(home, offset: int) -> tuple:
    """(records, new offset): the complete lines of the owner inbox after byte `offset`. The
    inbox is append-only, so a byte offset is a cursor no reordering can skip (a record appended
    while a turn reads, or a spooled one delivered late, lies past it: REVIEW L5-R2 K-16); a line
    still being written (no newline yet) is left for the next read."""
    try:
        with open(inbox_path(home), "rb") as fh:
            fh.seek(max(0, int(offset)))
            data = fh.read()
    except OSError:
        return [], max(0, int(offset))
    end = data.rfind(b"\n") + 1
    out = []
    for ln in data[:end].splitlines():
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out, max(0, int(offset)) + end


def _to_inbox(home, rec: dict) -> str:
    p = inbox_path(home)
    for x in (p.parent.parent, p.parent):
        x.mkdir(parents=True, exist_ok=True, mode=0o700)
    _append(p, json.dumps(rec, sort_keys=True) + "\n")
    return "chat owner inbox (shown at the owner's next turn in every konstant dsh session)"


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
            if rec.get("session"):
                try:
                    rec["session"] = session_id(rec["session"])
                except ValueError:          # the origin is a label only; the inbox is one file
                    rec["session"] = ""
            return _to_inbox(cfg.home, rec)
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


def mirror(cfg, rec: dict) -> str:
    """The second channel ([notify] mirror): every escalation is told there too. A failure is
    told locally and returned, never raised: the primary channel decides about the halt."""
    n = cfg.data["notify"]
    kind = n.get("mirror") or ""
    if not kind or kind == n["kind"] and not n.get("mirror_url"):
        return ""
    try:
        return "mirror " + deliver(cfg, rec, kind=kind, url=n.get("mirror_url") or n["url"])
    except NotifyError as exc:
        local(cfg, f"mirror {kind} did not take {text_of(rec)} ({exc})")
        return f"mirror {kind} failed: {exc}"


def emit(cfg, event: str, goal: str = "", job=None, display_id: str = "",
         reason: str = "", client=None) -> dict:
    """Record one event and deliver it when it is a new escalation. Never raises on a failed
    delivery (the event is spooled; the loop halts on a non-empty spool). Returns the record."""
    from konstant.board.redact import redact
    if event not in ESCALATIONS + OUTCOMES + (TEST,):
        raise ValueError(f"unknown factory event {event!r}")
    d = factory_dir(cfg.home)
    line = " ".join(redact(str(reason or "")).split())[:500]
    esc = event in ESCALATIONS
    if esc and client is None:
        client = factory_client(cfg)
    chat = cfg.data["notify"]["kind"] == "chat"
    session = _session_of(client, goal) if esc and chat else ""
    with open(d / "events.lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        rec = {"id": len(read_events(cfg.home)) + 1, "event": event,
               "kind": "escalation" if esc else "test" if event == TEST else "outcome",
               "goal": goal or None, "job": job, "display_id": display_id or None,
               "reason": line, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "board_url": cfg.base_url}
        if esc:
            rec["escalation"], new = _register(client, rec)
            if not new:
                rec["suppressed"] = True          # open and unacknowledged: told once
        _append(d / "events.jsonl", json.dumps(rec, sort_keys=True) + "\n")
    if not (esc or event == TEST) or rec.get("suppressed"):
        return rec
    if session:
        rec["session"] = session
    try:
        where = deliver(cfg, rec)
    except NotifyError as exc:
        _spool(cfg, rec, str(exc))
        local(cfg, f"undelivered {text_of(rec)} ({exc}): spooled; the factory halts")
        rec["undelivered"] = str(exc)
        rec["mirror"] = mirror(cfg, rec)
        return rec
    rec["delivered"] = where
    rec["mirror"] = mirror(cfg, rec)
    if not chat:            # chat: delivered when an owner turn SHOWS it (chat.turn, K-08)
        _mark(client, rec, where)
    return rec


def _mark(client, rec: dict, where: str) -> None:
    if client is not None and rec.get("escalation"):
        try:
            client.post(f"/api/factory/escalations/{rec['escalation']}/delivered", {"to": where})
        except Exception:  # noqa: BLE001 - delivered is what matters; the mark is bookkeeping
            pass


def test(cfg, kind: str = "", url: str = "") -> dict:
    """`konstant notify test`: one TEST event through the real channel (and the mirror). Under
    chat it is a real event of events.jsonl in the real owner inbox, so the next turn of EVERY
    `konstant dsh` session shows it: the end-to-end proof (REVIEW L5-R2 K-05). NotifyError when
    the channel refuses."""
    kind = kind or cfg.data["notify"]["kind"]
    d = factory_dir(cfg.home)
    with open(d / "events.lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        rec = {"id": len(read_events(cfg.home)) + 1, "event": TEST, "kind": "test",
               "goal": None, "job": None, "display_id": None,
               "reason": "konstant notify test: the notifier reaches you",
               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "board_url": cfg.base_url}
        _append(d / "events.jsonl", json.dumps(rec, sort_keys=True) + "\n")
    where = deliver(cfg, rec, kind=kind, url=url)
    return {"delivered": where, "kind": kind, "mirror": mirror(cfg, rec), "id": rec["id"]}


def selftest(cfg) -> str | None:
    """doctor's end-to-end check of the chat route, in a scratch copy of var/factory: the
    notifier's writer and `chat turn`'s reader, the one session-id scheme, a record shown exactly
    once per session and to a second session too. -> why it fails, or None."""
    import copy
    import shutil
    import tempfile
    from konstant.factory import chat
    tmp = tempfile.mkdtemp(prefix="konstant-notify-")
    try:
        c2 = copy.copy(cfg)
        c2.home = Path(tmp)
        c2.data = {**cfg.data, "notify": {**cfg.data["notify"], "kind": "chat", "mirror": ""}}
        got = test(c2, "chat")
        seen = []
        for sid in ("doctor-a", "doctor-b", "doctor-a"):
            sid = session_id(sid)
            chat._write_cursor(c2.home, sid, chat._read_cursor(c2.home, sid) or
                               {"inbox": 0, "events": 0})
            recs, cur, _ev, _old = chat.escalations_for(c2, None, sid)
            chat._write_cursor(c2.home, sid, cur)
            seen.append([r["id"] for r in recs])
        if seen != [[got["id"]], [got["id"]], []]:
            return f"the owner inbox did not reach every session exactly once ({seen})"
        return None
    except (OSError, ValueError, NotifyError) as exc:
        return f"the chat route failed in a scratch workspace: {exc}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def factory_down(cfg, minutes: int, why: str) -> dict:
    """The board has been unreachable for `minutes` (REVIEW L5-R2 K-13): told on stderr, in
    notify.log, through the mirror and, when it needs no board, the primary channel. Not an
    event of events.jsonl (its ids belong to the board's escalations); once per outage."""
    rec = {"id": 0, "event": "HALTED", "kind": "escalation", "goal": None, "job": None,
           "display_id": None, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "board_url": cfg.base_url,
           "reason": f"factory down: the board at {cfg.base_url} has been unreachable for "
                     f"{minutes} min ({why[:200]}); the factory waits and retries"}
    local(cfg, text_of(rec))
    out = {"mirror": mirror(cfg, rec)}
    if cfg.data["notify"]["kind"] in ("file", "webhook", "stdout"):
        try:
            out["primary"] = deliver(cfg, rec)
        except NotifyError as exc:
            out["primary"] = f"failed: {exc}"
    return out


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
        if cfg.data["notify"]["kind"] != "chat":
            _mark(client, rec, where)
    return left
