"""`konstant doctor` rows for factory mode (docs/LEVEL5.md 2.1, 2.2, 3.4).

  factory jail       every phase of a job with sealed holdouts runs in konstant's jail, on any
                     harness; without the jail such a job refuses to start (exit 2)
  factory harness    per configured harness: confined in factory mode, and whether its home is
                     relocated per phase (only such a harness may run the scenario writer)
  claude sandbox     (claude configured) whether Claude Code's own sandbox runs nested inside the
                     jail, or the jail is the boundary with Claude Code's sandbox off
  identities         the factory identities' tokens: present, 0600
  scenario writer    the harness the scenario writer runs on (refused when its home cannot be
                     relocated); one model for every role is INFO, never a WARN (owner Q1)
  chat intake        whether the dsh orchestrator chat is the intake ([notify] kind = chat and
                     goal_roles with orchestrator)
"""
from __future__ import annotations

import os
import shutil
import stat


def rows(cfg) -> list:
    from konstant import harnesses
    from konstant import jail as jail_mod
    from konstant.board.policy import IDENTITIES
    out = []
    on = bool(cfg.data["gate"]["jail"])
    from konstant.holdout import store as store_mod
    leak = store_mod.jail_proof(cfg) if on and jail_mod.available() else None
    if leak:                                  # the claim is checked, not asserted (REVIEW H-04)
        out.append(("FAIL", "factory jail", leak))
    elif on and jail_mod.available():
        out.append(("PASS", "factory jail", "a job with sealed holdouts runs every phase in "
                    "konstant's jail on any harness (claude, codex, gemini, dsh, command): its "
                    "own job clone writable, the target read-only, only its own identity's token "
                    "readable, the holdout store masked (listed from inside a jail: empty)"))
    else:
        out.append(("WARN", "factory jail", "konstant's jail is " + (
            "off ([gate] jail = false)" if not on else "unavailable (no working bubblewrap)")
            + ": a job with sealed holdouts refuses to start (exit 2, `holdouts need a confined "
            "phase`); nothing falls back to unconfined phases"))
    names = harnesses.configured(cfg.data["harness"])
    parts, fixed = [], []
    for name in names:
        ad = harnesses.adapter(name)
        parts.append(f"{name}: {ad.home_doc}")
        if not ad.relocatable_home:
            fixed.append(name)
    if fixed:
        out.append(("INFO", "factory harness", "; ".join(parts) + f". {', '.join(fixed)} cannot "
                    "relocate its home per phase: never used for the scenario writer (its "
                    "transcript would stay readable to a later producer)"))
    else:
        out.append(("PASS", "factory harness", "; ".join(parts)))
    if "claude" in names:
        out.append(claude_row(cfg.home, cfg.confinement().host_write))
    out.append(identities_row(cfg, IDENTITIES))
    return out


def loop_rows(cfg) -> list:
    """`factory` (the loop: running, stale heartbeat, halted, kill switch) and `notifier`
    (docs/LEVEL5.md 6.3, 6.4)."""
    from konstant.factory import notify, proc
    st = proc.state(cfg.home, cfg.data["factory"]["tick_s"])
    hb = st["heartbeat"] or {}
    spool = notify.spooled(cfg.home)
    if spool:
        row = ("FAIL", "factory", f"{len(spool)} undelivered escalation(s) in var/factory/spool/:"
               " the factory is halted until `konstant --as owner factory resume` delivers them")
    elif st["state"] == "stale":
        row = ("WARN", "factory", f"the loop (pid {st['pid']}) wrote no heartbeat for three ticks"
               f" (last {hb.get('at', '?')}): it is hung or overloaded; `factory status`")
    elif st["state"] in ("running", "draining"):
        row = ("PASS", "factory", f"the loop runs (pid {st['pid']}, {st['state']}, last tick "
               f"{hb.get('at', '?')})")
    else:
        row = ("INFO", "factory", "the loop is not running (`konstant factory start`, or the "
               "unit `factory install-unit` writes)" + ("; the kill switch is set: `factory "
                                                        "resume` clears it" if st["stop"] else ""))
    n = cfg.data["notify"]
    where = {"stdout": "the factory process's stderr", "file": "var/factory/notify.log",
             "webhook": f"POST to {n['url'] or '?'}",
             "chat": "the orchestrator session the goal came from"}.get(n["kind"], n["kind"])
    why = notify.check_url(n["url"], n["url_hosts"]) if n["kind"] == "webhook" else None
    note = ("FAIL", "notifier", why) if why else (
        "PASS", "notifier", f"escalations go to {where} ({n['retries']} retr(y/ies)); one per "
        "(goal, job, event) until `factory ack`; a failed delivery halts the factory")
    return [row, note]


def intake_rows(cfg) -> list:
    """The level-5 intake rows (wave L5-3): the scenario writer's harness and the chat intake."""
    return [writer_row(cfg), intake_row(cfg)]


def writer_row(cfg) -> tuple:
    """Which harness the scenario writer runs on, refused when it cannot relocate its home
    (docs/LEVEL5.md 3.4); one model for every role is supported (owner decision Q1)."""
    from konstant import catalog as catalog_mod
    from konstant.holdout import author
    try:
        cat = catalog_mod.load(catalog_mod.find_root(cfg.home, cfg.data["catalog"]["path"]))
        hv, _ad = author.writer_harness(cfg, cat)
    except author.AuthorRefused as exc:
        return ("WARN", "scenario writer", f"{exc}: `konstant intake` files the jobs but every "
                "job's holdout authoring escalates BLOCKED until [holdout] writer_harness names one")
    except Exception as exc:  # noqa: BLE001 - a row, never a crash of doctor
        return ("INFO", "scenario writer", f"not checked: {exc}")
    same = not cfg.data["holdout"]["writer_harness"] and not cfg.data["holdout"]["writer_model"]
    return ("INFO", "scenario writer", f"runs on {hv.name}"
            + (f" (model {hv.model})" if hv.model else "") + ", jailed, home relocated into the "
            "sealed store and deleted after the phase; "
            + ("the same harness and model as every other role: supported (separation by "
               "identity, context and isolation; docs/LEVEL5.md §9 Q1)" if same else
               "[holdout] writer_harness / writer_model set"))


def intake_row(cfg) -> tuple:
    """Whether the owner's orchestrator chat is the intake (docs/LEVEL5.md 4.0)."""
    chat = cfg.data["notify"]["kind"] == "chat"
    orch = "orchestrator" in cfg.data["factory"]["goal_roles"]
    if chat and orch:
        return ("PASS", "chat intake", "[notify] kind = chat and goal_roles include the "
                "orchestrator: a typed request in `konstant dsh` becomes a goal proposal, filed "
                "on the owner's next-message yes; escalations come back in that chat")
    if chat:
        return ("WARN", "chat intake", "[notify] kind = chat but [factory] goal_roles lacks "
                "orchestrator: the session shows the intake block, yet its `goal add "
                "--from-chat` is refused; add \"orchestrator\" to goal_roles")
    return ("INFO", "chat intake", f"off ([notify] kind = {cfg.data['notify']['kind']}): goals "
            "come from `konstant goal add FILE` (owner); set [notify] kind = \"chat\" and "
            "goal_roles = [\"owner\", \"orchestrator\"] to make the dsh chat the intake")


def claude_row(home=None, host_tmp: bool = False) -> tuple:
    """`host_tmp`: the confinement shares the host /tmp with phases (host_write), so a phase has
    no short private /tmp and Claude Code's sandbox cannot nest (docs/CONCEPTS.md)."""
    import sys

    from konstant import jail as jail_mod
    from konstant.harnesses.base import private_tmp
    from konstant.harnesses.claude import sandbox_nests
    if sandbox_nests(home) and not host_tmp:
        return ("PASS", "claude sandbox", "factory mode: Claude Code's own Bash sandbox runs "
                "nested inside konstant's jail" + ("" if sys.platform != "darwin" else
                                                   " (macOS: Seatbelt)"))
    nested = "starts" if jail_mod.nests() else "does not start"
    socat = "present" if shutil.which("socat") else "missing"
    tmp = "" if home is None or private_tmp(home) else ("; the workspace is under /tmp, so a "
                                                        "phase has no short private /tmp")
    if host_tmp:
        tmp += "; [confinement] host_write shares the host /tmp with phases"
    return ("INFO", "claude sandbox", f"factory mode: Claude Code's sandbox cannot run inside "
            f"konstant's jail here (a nested bubblewrap {nested} in the jail; socat {socat}"
            f"{tmp}): a "
            "claude phase in factory mode runs with Claude Code's sandbox off and konstant's jail "
            "as the boundary")


def identities_row(cfg, identities: dict) -> tuple:
    bad = []
    for label in identities:
        p = cfg.secrets_dir / f"{label}.token"
        if not p.exists():
            bad.append(f"{p.name} missing")
        elif stat.S_IMODE(os.stat(p).st_mode) != 0o600:
            bad.append(f"{p.name} is {oct(stat.S_IMODE(os.stat(p).st_mode))}")
    if bad:
        return ("WARN", "identities", "; ".join(bad) + ": `bin/konstant board init` mints the "
                "factory identities (planner, dod-reviewer, scenario, factory) without touching "
                "existing tokens")
    return ("PASS", "identities", f"{len(identities)} factory identity tokens (planner, "
            "dod-reviewer, scenario: worker; factory: orchestrator), 0600; the board refuses "
            "the identity pairs that must differ. One model may play every role (docs/LEVEL5.md "
            "§9 Q1): the separation is the identity, the context each phase gets and the jail's "
            "file isolation, not a second model")
