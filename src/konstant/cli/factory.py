"""`konstant factory run|start|stop|status|resume|ack|escalations|resume-shipping|install-unit`
and `konstant notify test` (docs/LEVEL5.md 6; factory/loop.py).

factory run [GOAL..]  the loop in the foreground (forever; --until-idle: exit 0 every goal done,
                      4 a goal ended in an escalation or the factory halted, 2 refused before the
                      start, 5 internal error; --once: one tick and its steps; --dry-run: print
                      what the first tick would do, change nothing)
factory start         the same loop in the background (var/factory/factory.pid, var/logs/
                      factory.log); refused (exit 2) while a factory runs: one per workspace
factory stop          the kill switch: var/factory/STOP; the loop starts nothing new, lets its
                      running steps finish and exits (--now: SIGTERM to the loop and its steps);
                      no factory starts while it is set
factory resume        clear the kill switch; a halted factory (a notifier that could not deliver,
                      an internal error): deliver the spooled events, then lift the halt (owner)
factory status        the loop (running|draining|stale|stopped), halt, shipping, goals, open
                      escalations, the last events
factory ack ID        (owner) acknowledge an escalation: the next one of its kind is told again
factory install-unit  write a systemd --user unit for the loop into var/factory/systemd/ and
                      print it; konstant never enables or starts it (that is the owner's step)
notify test           deliver one TEST event through [notify] (or --kind/--url)
All of it is refused inside a task run and in the orchestrator chat, except status.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from konstant.cli.main import EXIT_FAIL, EXIT_OK, EXIT_USAGE
from konstant.client import ClientError, in_chat, in_task


def _refused_here(what: str) -> bool:
    if in_task():
        print(f"konstant: refused: {what} is not available inside a task run "
              "(KONSTANT_IN_TASK=1): a phase never drives the factory", file=sys.stderr)
        return True
    if in_chat():
        print(f"konstant: refused: {what} is the factory's step, not the orchestrator chat's "
              "(KONSTANT_CHAT_SESSION is set)", file=sys.stderr)
        return True
    return False


def _switch(home) -> str | None:
    from konstant.factory import proc
    s = proc.stopped_by(home)
    if s is None:
        return None
    return (f"the factory's kill switch is set (var/factory/STOP, {s.get('reason') or 'stop'} "
            f"at {s.get('at') or '?'}): `konstant factory resume` clears it")


def cmd_run(ctx) -> int:
    a, cfg = ctx.args, ctx.cfg
    if _refused_here("factory run"):
        return EXIT_USAGE
    from konstant.factory import loop, proc
    mode = "once" if a.once else "until_idle" if a.until_idle else "forever"
    f = loop.Factory(cfg, a.goal, mode=mode, harness=a.harness)
    if a.dry_run:
        try:
            f.preflight()
            _p, acts = f.plan()
        except (loop.Refused, ClientError) as exc:
            print(f"konstant factory: refused: {getattr(exc, 'message', exc)}", file=sys.stderr)
            return EXIT_USAGE
        rows = [{"action": x.kind, "goal": x.goal, "job": x.job, "display_id": x.display_id,
                 "event": x.event or None, "reason": x.reason} for x in acts]
        ctx.out({"actions": rows, "goals": f.states}, "\n".join(
            f"{r['action']:<9} {r['goal']} {('job ' + r['display_id']) if r['job'] else ''}: "
            f"{r['reason']}" for r in rows) or "nothing to do")
        return EXIT_OK
    fh = proc.lock(cfg.home)
    if fh is None:
        pid = proc.running_pid(cfg.home)
        print(f"konstant factory: refused: a factory already runs (pid {pid or '?'}): one per "
              "workspace", file=sys.stderr)
        return EXIT_USAGE
    try:
        why = _switch(cfg.home)
        if why:
            print(f"konstant factory: refused: {why}", file=sys.stderr)
            return EXIT_USAGE
        os.chdir(cfg.home)
        from konstant.factory.notify import factory_dir
        factory_dir(cfg.home)
        proc.pid_file(cfg.home).write_text(f"{os.getpid()}\n")
        try:
            f.preflight()
        except (loop.Refused, ClientError) as exc:
            print(f"konstant factory: refused: {getattr(exc, 'message', exc)}", file=sys.stderr)
            return EXIT_USAGE
        print(f"konstant factory: running (pid {os.getpid()}, tick {f.tick_s}s, cap {f.cap} "
              f"model step(s), mode {mode})", file=sys.stderr, flush=True)
        rc = f.run()
        ctx.out({"exit": rc, "goals": f.states, "ticks": f.ticks},
                f"konstant factory: exit {rc}; goals: " + (", ".join(
                    f"{k} {v}" for k, v in sorted(f.states.items())) or "none"))
        return rc
    finally:
        try:
            if proc.pid_file(cfg.home).read_text().strip() == str(os.getpid()):
                proc.pid_file(cfg.home).unlink()
        except OSError:
            pass
        fh.close()


def cmd_start(ctx) -> int:
    a, cfg = ctx.args, ctx.cfg
    if _refused_here("factory start"):
        return EXIT_USAGE
    from konstant.factory import proc
    pid = proc.running_pid(cfg.home)
    if pid:
        print(f"konstant factory: refused: a factory already runs (pid {pid}): one per "
              "workspace", file=sys.stderr)
        return EXIT_USAGE
    why = _switch(cfg.home)
    if why:
        print(f"konstant factory: refused: {why}", file=sys.stderr)
        return EXIT_USAGE
    (cfg.var / "logs").mkdir(parents=True, exist_ok=True)
    log = cfg.var / "logs" / "factory.log"
    cmd = [sys.executable, "-m", "konstant", "factory", "run", *a.goal]
    if a.harness:
        cmd += ["--harness", a.harness]
    env = dict(os.environ, KONSTANT_HOME=str(cfg.home))
    size = log.stat().st_size if log.exists() else 0
    with open(log, "ab") as fh:
        p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             env=env, cwd=str(cfg.home), start_new_session=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if p.poll() is not None:
            tail = log.read_bytes()[size:].decode("utf-8", "replace").strip().splitlines()[-5:]
            print("\n".join(tail), file=sys.stderr)
            return p.returncode
        hb = proc.read_json(proc.heartbeat_file(cfg.home)) or {}
        if hb.get("pid") == p.pid and hb.get("tick", 0) >= 1:
            ctx.out({"pid": p.pid, "state": "running", "log": str(log)},
                    f"factory started (pid {p.pid}); log {log}")
            return EXIT_OK
        time.sleep(0.2)
    ctx.out({"pid": p.pid, "state": "starting", "log": str(log)},
            f"factory starting (pid {p.pid}); no heartbeat yet, log {log}")
    return EXIT_OK


def cmd_stop(ctx) -> int:
    a, cfg = ctx.args, ctx.cfg
    if _refused_here("factory stop"):
        return EXIT_USAGE
    from konstant.factory import proc
    proc.set_stop(cfg.home, os.environ.get("USER", "?"), "factory stop" + (" --now" if a.now
                                                                            else ""))
    pid = proc.running_pid(cfg.home)
    if pid is None:
        ctx.out({"state": "stopped", "kill_switch": True},
                "factory stopped (not running); the kill switch is set: `factory resume` "
                "clears it")
        return EXIT_OK
    if a.now:
        try:
            os.killpg(pid, signal.SIGTERM) if os.getpgid(pid) == pid else \
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + a.wait
    while time.monotonic() < deadline and proc.running_pid(cfg.home) == pid:
        time.sleep(0.2)
    if proc.running_pid(cfg.home) == pid:
        ctx.out({"state": "draining", "pid": pid}, f"factory draining (pid {pid}): its running "
                "step(s) finish first; `factory stop --now` ends them")
        return EXIT_OK
    ctx.out({"state": "stopped", "pid": pid, "kill_switch": True},
            f"factory stopped (pid {pid}); the kill switch stays set until `factory resume`")
    return EXIT_OK


def cmd_resume(ctx) -> int:
    cfg = ctx.cfg
    if _refused_here("factory resume"):
        return EXIT_USAGE
    from konstant.factory import notify, proc
    cleared = proc.stopped_by(cfg.home) is not None
    proc.stop_file(cfg.home).unlink(missing_ok=True)
    c = ctx.client("viewer")
    h = c.get("/api/factory/halt")
    left = notify.spooled(cfg.home)
    if h["halted"] or left:
        left = notify.redeliver(cfg)
        if left:
            print(f"konstant factory: still halted: {len(left)} event(s) undelivered "
                  f"({left[0].get('undelivered')}); fix [notify], then resume again",
                  file=sys.stderr)
            return 4
        if h["halted"]:
            ctx.client(ctx.args.as_role or "owner").post(
                "/api/factory/halt", {"action": "resume", "reason": "resumed by the owner"})
    ctx.out({"kill_switch_cleared": cleared, "halt_lifted": bool(h["halted"])},
            "factory may run again" + (" (kill switch cleared)" if cleared else "")
            + (" (halt lifted)" if h["halted"] else "") + ": `konstant factory start`")
    return EXIT_OK


def cmd_status(ctx) -> int:
    cfg = ctx.cfg
    from konstant.factory import proc
    local = proc.state(cfg.home, cfg.data["factory"]["tick_s"])
    try:
        c = ctx.client("viewer")
        st, sh = c.get("/api/factory/status"), c.get("/api/factory/shipping")
    except ClientError as exc:
        print(f"konstant: {exc.message}", file=sys.stderr)
        return EXIT_USAGE
    res = {**st, **sh, "state": st["factory"]["state"]}
    f = st["factory"]
    lines = [f"factory {f['state']}" + (f" (pid {f['pid']})" if f["pid"] else "")
             + (f", last tick {f['last_tick']}" if f.get("last_tick") else "")
             + (" - kill switch set" if local["stop"] else "")
             + (f" - HALTED since {st['halt']['since']}: {st['halt']['reason']}"
                if st["halted"] else ""),
             f"shipping {sh['shipping']}" + (f" since {sh['since']}: {sh['reason']}"
                                             if sh["shipping"] == "halted" else "")
             + ("; ships: " + ", ".join(f"{k} {v}" for k, v in sorted(st["ships"].items()))
                if st["ships"] else "")]
    lines += [f"goal {g['goal']}: {g['status']} (intake {g['intake']})" for g in st["goals"]]
    lines.append(f"open escalations {st['open_escalations']}; spooled {st['spooled']}")
    lines += [f"  {e['at']} {e['event']} {e.get('goal') or '-'}: {e['reason']}"
              for e in st["events"][-5:]]
    ctx.out(res, "\n".join(lines))
    return EXIT_OK


def cmd_ack(ctx) -> int:
    if _refused_here("factory ack"):
        return EXIT_USAGE
    res = ctx.client(ctx.args.as_role or "owner").post(f"/api/factory/escalations/{ctx.args.id}"
                                                      "/ack")
    ctx.out(res, f"escalation {res['id']} ({res['kind']} {res.get('goal') or '-'}) "
                 f"acknowledged by {res['acked_by']}")
    return EXIT_OK


def cmd_escalations(ctx) -> int:
    rows = ctx.client("viewer").get("/api/factory/escalations",
                                    open="true" if ctx.args.open else "")["escalations"]
    ctx.out(rows, "\n".join(
        f"{e['id']:<4} {'open ' if e['open'] else 'acked'} {e['kind']:<15} {e.get('goal') or '-'}"
        f"{(' job ' + e['display_id']) if e.get('display_id') else ''}: {e['reason']}"
        for e in rows) or "no escalations")
    return EXIT_OK


def cmd_resume_shipping(ctx) -> int:
    if _refused_here("factory resume-shipping"):
        return EXIT_FAIL
    res = ctx.client(ctx.args.as_role or "owner").post(
        "/api/factory/shipping", {"action": "resume", "reason": "resumed by the owner"})
    ctx.out(res, f"shipping {res['shipping']}")
    return EXIT_OK


def cmd_install_unit(ctx) -> int:
    from konstant.factory import unit
    path, text = unit.write(ctx.cfg)
    ctx.out({"path": str(path), "unit": text, "enabled": False}, text + "\n" + unit.howto(path))
    return EXIT_OK


def cmd_notify_test(ctx) -> int:
    from konstant.factory import notify
    cfg = ctx.cfg
    rec = {"id": 0, "event": "TEST", "kind": "escalation", "goal": None, "job": None,
           "display_id": None, "reason": "konstant notify test: the notifier reaches you",
           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "board_url": cfg.base_url}
    kind = ctx.args.kind or cfg.data["notify"]["kind"]
    try:
        where = notify.deliver(cfg, rec, kind=kind, url=ctx.args.url or "")
    except notify.NotifyError as exc:
        print(f"konstant notify: FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    ctx.out({"delivered": where, "kind": kind}, f"konstant notify: delivered to {where}")
    return EXIT_OK


def register(sub, leaf) -> None:
    f = sub.add_parser("factory", help="level 5: the factory loop, its state and its switches")
    fs = f.add_subparsers(dest="factory_cmd", metavar="VERB")
    fs.required = True
    for verb, func, help_ in (("run", cmd_run, "the factory loop in the foreground"),
                              ("start", cmd_start, "the factory loop in the background")):
        p = fs.add_parser(verb, parents=[leaf], help=help_)
        p.add_argument("goal", nargs="*", help="only these goals (default: every goal)")
        p.add_argument("--harness", help="an adapter name or an argv template for every phase")
        if verb == "run":
            g = p.add_mutually_exclusive_group()
            g.add_argument("--until-idle", action="store_true", help="exit when no goal has "
                           "work left (0 all done, 4 an escalation)")
            g.add_argument("--once", action="store_true", help="one tick and its steps")
            p.add_argument("--dry-run", action="store_true", help="print what the first tick "
                           "would do; change nothing")
        p.set_defaults(func=func)
    p = fs.add_parser("stop", parents=[leaf], help="set the kill switch: drain and exit")
    p.add_argument("--now", action="store_true", help="also SIGTERM the loop and its steps")
    p.add_argument("--wait", type=float, default=60, help="seconds to wait for the exit")
    p.set_defaults(func=cmd_stop)
    for verb, func, help_ in (
            ("resume", cmd_resume, "clear the kill switch; redeliver and lift a halt (owner)"),
            ("status", cmd_status, "the loop, halt, shipping, goals, escalations"),
            ("resume-shipping", cmd_resume_shipping, "(owner) lift the halt a failed rollback "
             "set"),
            ("install-unit", cmd_install_unit, "write (never enable) a systemd --user unit")):
        p = fs.add_parser(verb, parents=[leaf], help=help_)
        p.set_defaults(func=func)
    p = fs.add_parser("ack", parents=[leaf], help="(owner) acknowledge an escalation")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_ack)
    p = fs.add_parser("escalations", parents=[leaf], help="the escalations, with their ids")
    p.add_argument("--open", action="store_true", help="only the unacknowledged ones")
    p.set_defaults(func=cmd_escalations)
    n = sub.add_parser("notify", help="level 5: the factory's notifier")
    ns = n.add_subparsers(dest="notify_cmd", metavar="VERB")
    ns.required = True
    p = ns.add_parser("test", parents=[leaf], help="deliver one TEST event")
    p.add_argument("--kind", choices=("stdout", "file", "webhook", "chat"))
    p.add_argument("--url", help="the webhook URL (default [notify] url)")
    p.set_defaults(func=cmd_notify_test)
