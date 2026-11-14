"""Owner actions asked for in the orchestrator chat (REVIEW L5-R2 K-07; docs/LEVEL5.md 4.0).

The orchestrator session is a model that reads untrusted text (pages, repository files, job
output). It holds no owner power: inside it (KONSTANT_CHAT_SESSION set, the konstant-gate plugin
marks the session's own shell) the owner and verifier tokens are refused (client.token_for), and
`chat turn` itself is refused, so a model cannot confirm its own proposal.

The owner's verbs - `factory ack ID`, `factory resume`, `factory resume-shipping`,
`ship JOB --approve-decision`, `goal pause|resume|cancel GOAL` - run from the chat only as a
PROPOSAL: the command records it (var/factory/chat/owner/<session>.json, konstant's own wording
built from validated ids) and prints it; konstant carries it out with the owner token when, and
only when, the owner's NEXT message in that session is a plain yes, which `chat turn` (run by the
plugin on the owner's genuine message, never by the model) reads exactly like the goal yes. Any
other reply drops it. One proposal per session; a goal proposal and an owner action open at the
same time are both dropped on a bare yes (it would be unclear which one the yes means).

Limit (stated, as for the goal yes): the session runs unjailed as the owner's own OS user, so a
model that deliberately strips the marker and reads var/secrets/owner.token itself is not stopped
by konstant; the marker stops every ordinary command path and makes the confirmation konstant's.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

VERBS = ("ack", "factory-resume", "resume-shipping", "approve-decision", "goal-pause",
         "goal-resume", "goal-cancel")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def path(home, session: str) -> Path:
    return Path(home) / "var" / "factory" / "chat" / "owner" / f"{session}.json"


def describe(verb: str, ref: str, commit: str = "") -> str:
    """konstant's own wording of an owner action (ids only, validated)."""
    return {"ack": f"acknowledge escalation {ref}",
            "factory-resume": "resume the factory (clear the kill switch, redeliver, lift a halt)",
            "resume-shipping": "resume shipping after a failed rollback",
            "approve-decision": f"approve shipping job {ref} at its verified commit {commit[:12]}",
            "goal-pause": f"pause goal {ref}", "goal-resume": f"resume goal {ref}",
            "goal-cancel": f"cancel goal {ref} for good"}[verb]


def propose(cfg, session: str, verb: str, ref: str = "", commit: str = "") -> dict:
    if verb not in VERBS:
        raise ValueError(f"not an owner action: {verb}")
    if ref and not _REF.fullmatch(str(ref)):
        raise ValueError(f"not an id: {ref!r}")
    rec = {"verb": verb, "ref": str(ref), "commit": commit, "session": session,
           "text": describe(verb, str(ref), commit),
           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    p = path(cfg.home, session)
    for d in (p.parent.parent, p.parent):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(rec, sort_keys=True))
    tmp.replace(p)
    return rec


def pending(home, session: str) -> dict | None:
    try:
        rec = json.loads(path(home, session).read_text())
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("verb") in VERBS else None


def drop(home, session: str) -> None:
    path(home, session).unlink(missing_ok=True)


def factory_resume(cfg, owner) -> str:
    """Clear the kill switch, redeliver the spool, lift a halt (the owner's `factory resume`)."""
    from konstant.factory import notify, proc
    owner.post("/api/factory/switch", {"action": "resume"})
    cleared = proc.stopped_by(cfg.home) is not None
    proc.stop_file(cfg.home).unlink(missing_ok=True)
    h = owner.get("/api/factory/halt")
    if h["halted"] or notify.spooled(cfg.home):
        left = notify.redeliver(cfg)
        if left:
            return f"still halted: {len(left)} event(s) undelivered"
        if h["halted"]:
            owner.post("/api/factory/halt", {"action": "resume", "reason": "resumed by the owner"})
    return "factory may run again" + (" (kill switch cleared)" if cleared else "") + \
        (" (halt lifted)" if h["halted"] else "")


def execute(cfg, owner, rec: dict) -> str:
    """Carry out a confirmed owner action with the owner client; -> what happened."""
    verb, ref = rec["verb"], rec["ref"]
    if verb == "ack":
        owner.post(f"/api/factory/escalations/{ref}/ack")
        return f"escalation {ref} acknowledged"
    if verb == "factory-resume":
        return factory_resume(cfg, owner)
    if verb == "resume-shipping":
        owner.post("/api/factory/shipping", {"action": "resume", "reason": "resumed by the owner "
                                                                           "in the chat"})
        return "shipping resumed"
    if verb == "approve-decision":
        owner.post(f"/api/jobs/{ref}/ship-decision", {"commit": rec["commit"],
                                                      "reason": "owner decision in the chat"})
        return f"job {ref} approved at {rec['commit'][:12]}: the factory ships it on its next tick"
    res = owner.post(f"/api/goals/{ref}/{verb.split('-', 1)[1]}")
    return f"goal {res.get('slug', ref)} {res.get('status', '')}".strip()
