"""The orchestrator chat as intake and as the place reports come back to (docs/LEVEL5.md 4.0).

`konstant chat turn --session ID -` is what the konstant-gate dsh plugin runs on EVERY owner
message of the orchestrator session (depth 0, a genuine user message; never a child, a nudge or a
tool result) when `[notify] kind = "chat"`. Deterministic, no model:

1. A goal this session proposed (`goal add --from-chat`, status `proposed`) is decided by THIS
   message: a plain yes (yes, y, ja, ok, go, confirm, file it, ...) confirms it (the board writes
   the goal copy, status active, source chat); anything else withdraws it. So a goal starts only
   from a message the owner sent in that session, right after the one-line confirmation (4.0
   step 2); text inside a phase log, a web page or a file is never such a message.
2. New escalations of this session's goals (and of goals filed from a file) since the session's
   cursor (var/factory/chat/<session>.json) become lines shown at the start of the turn; new
   outcomes are summed up in one line (details on request: `konstant goal show`).
3. A typed task (the classifier) without an explicit `[type:..]` or `[job:..]` tag becomes the
   INTAKE block: the orchestrator turns it into a goal proposal instead of doing the work in the
   chat. A tagged task keeps the level-4 gate.
Refused inside a task run (KONSTANT_IN_TASK=1): a phase never confirms or proposes a goal.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

YES = re.compile(r"^\s*(yes|y|yeah|yep|ja|j|ok|okay|go|go ahead|confirm(ed)?|file it|do it|"
                 r"sure|approved?)\s*[.!]*\s*$", re.I)
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
TAGGED = re.compile(r"\[(type|job):[^\]]+\]", re.I)


def cursor_path(home, session: str) -> Path:
    return Path(home) / "var" / "factory" / "chat" / f"{session}.json"


def _read_cursor(home, session: str) -> int:
    try:
        return int(json.loads(cursor_path(home, session).read_text())["seen"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def _write_cursor(home, session: str, seen: int) -> None:
    p = cursor_path(home, session)
    for d in (p.parent.parent, p.parent):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps({"seen": seen}))
    tmp.replace(p)


def intake_block(cfg, session: str, projects: list) -> str:
    k = Path(cfg.home) / "bin" / "konstant"
    names = ", ".join(p["slug"] for p in projects) or "none yet: `konstant project add` first"
    d = cfg.data["factory"]["defaults"]
    return "\n".join([
        "=== KONSTANT INTAKE (this chat is the intake; docs/LEVEL5.md 4.0) ===",
        "The owner asked for work. Do not do the work in this chat and write no code: turn the "
        "request into a goal for the factory.",
        f"1. Pick the project (one of: {names}), a short goal id (a-z, 0-9, -), the goal text "
        "(what the owner asked, complete) and the limits the owner named (else the defaults: "
        f"max_attempts = {d.get('max_attempts', 3)}).",
        "2. In THIS turn, before you end it, run the command below. It only records a "
        "PROPOSAL: nothing is filed until the owner's next message says yes, and that yes is "
        "read by konstant itself, so never wait for a yes before running it:",
        f"   {k} goal add - --from-chat --session {session} <<'EOF'",
        "   [goal]", '   id = "<goal-id>"', '   project = "<project>"',
        '   text = """<the goal>"""', "   [limits]",
        f"   max_attempts = {d.get('max_attempts', 3)}", "   EOF",
        "3. Then tell the owner in ONE line what you proposed (project, goal text, limits) and "
        "that his yes files it, and end your turn. On his yes konstant files it; the factory "
        "(not you: never run `konstant intake` from this chat) plans the jobs, reviews their "
        "DoD, seals holdouts and reports back here.",
        "=== END KONSTANT INTAKE ==="])


def turn(cfg, client, session: str, text: str) -> dict:
    """One owner message of the orchestrator session -> {lines, intake, block, confirmed,
    withdrawn}. `client` acts as the orchestrator (the session's own role)."""
    from konstant import catalog as catalog_mod
    from konstant.factory import notify
    from konstant.gate import classify
    if not SESSION.fullmatch(session or ""):
        raise ValueError("chat turn needs the session id (--session)")
    out = {"lines": [], "intake": False, "block": "", "confirmed": None, "withdrawn": None}
    pending = client.get("/api/goals", status="proposed", session=session)["goals"]
    for g in pending:
        if YES.match(text or "") and g is pending[-1]:
            res = client.post(f"/api/goals/{g['slug']}/confirm", {"session": session})
            out["confirmed"] = g["slug"]
            out["lines"].append(f"konstant: goal {g['slug']} FILED from this chat (sha256 "
                                f"{res['spec_sha256'][:12]}): {res.get('summary', '')}. The "
                                "factory takes it in and reports here; nothing to run in this "
                                "chat.")
        else:
            client.post(f"/api/goals/{g['slug']}/withdraw",
                        {"session": session, "reason": "the owner's next message was not a yes"})
            out["withdrawn"] = g["slug"]
            out["lines"].append(f"konstant: goal proposal {g['slug']} withdrawn (your reply was "
                                "not a yes); nothing was filed")
    mine = {g["slug"] for g in client.get("/api/goals")["goals"]
            if g.get("session") == session or g.get("source") == "file"}
    seen = _read_cursor(cfg.home, session)
    new = [e for e in notify.read_events(cfg.home) if e.get("id", 0) > seen
           and e.get("goal") in mine]
    for e in new:
        if e["kind"] == "escalation":
            where = f" job {e.get('display_id') or e.get('job')}" if e.get("job") else ""
            out["lines"].append(f"konstant {e['event']}: goal {e['goal']}{where}: {e['reason']}")
    outcomes = [e for e in new if e["kind"] == "outcome"]
    if outcomes:
        out["lines"].append("konstant outcomes since your last turn: " + "; ".join(
            f"{e['event']} {e['goal']}" for e in outcomes) + " (details: `bin/konstant goal "
            "show <goal>`)")
    events = notify.read_events(cfg.home)
    if events:
        _write_cursor(cfg.home, session, max(e.get("id", 0) for e in events))
    if not TAGGED.search(text or "") and not out["confirmed"]:
        cat = catalog_mod.load(catalog_mod.find_root(cfg.home, cfg.data["catalog"]["path"]))
        t, _why = classify.classify(text or "", cat)
        if t is not None:
            out["intake"] = True
            out["block"] = intake_block(cfg, session, client.get("/api/projects")["projects"])
    return out
