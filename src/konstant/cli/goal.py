"""`konstant goal add|list|show|pause|resume|cancel`, `konstant intake GOAL` and `konstant chat
turn` (docs/LEVEL5.md 4.0-4.2).

goal add FILE|-     validate a goal file and file it (owner: active at once; the copy at
                    var/factory/goals/<id>.toml). `--from-chat --session ID`: the orchestrator's
                    proposal from the owner's chat ([factory] goal_roles), filed only when the
                    owner's next message in that session is a yes (`chat turn`).
intake GOAL         planner -> DoD review -> deterministic filing -> approval -> scenario writer
                    (factory/intake.py); exit 0 filed, 3 refused (nothing filed), 4 a job's
                    holdout authoring BLOCKED, 2 setup.
chat turn           one owner message of the orchestrator session (the konstant-gate plugin
                    runs it; factory/chat.py): confirm or withdraw this session's proposal, the
                    new escalations, the intake block for a typed request. JSON on stdout.
goal add, intake and chat turn are refused inside a task run (KONSTANT_IN_TASK=1).
"""
from __future__ import annotations

import json
import sys

from konstant.cli.main import EXIT_FAIL, EXIT_OK, EXIT_USAGE
from konstant.client import in_chat, in_task


def _no_task(what: str) -> bool:
    if in_task():
        print(f"konstant: refused: {what} is not available inside a task run (KONSTANT_IN_TASK=1): "
              "a goal comes only from the owner (or his chat), never from a phase",
              file=sys.stderr)
        return True
    return False


def _read(path: str) -> str:
    return sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()


def cmd_add(ctx) -> int:
    a = ctx.args
    if _no_task("goal add"):
        return EXIT_FAIL
    try:
        text = _read(a.file)
    except OSError as exc:
        print(f"konstant: cannot read {a.file}: {exc.strerror}", file=sys.stderr)
        return EXIT_USAGE
    if a.from_chat:
        session = a.session or in_chat()
        res = ctx.client(a.as_role or ctx.role).post(
            "/api/goals", {"spec": text, "source": "chat", "session": session})
        ctx.out(res, f"PROPOSED: goal {res['slug']}, {res['summary']} - filed when the owner "
                     "answers yes in this chat; any other reply withdraws it")
        return EXIT_OK
    res = ctx.client(a.as_role or "owner").post("/api/goals", {"spec": text, "source": "file"})
    ctx.out(res, f"goal {res['slug']} added (sha256 {res['spec_sha256']}): {res['summary']}; "
                 f"copy var/factory/goals/{res['slug']}.toml")
    return EXIT_OK


def _line(g: dict) -> str:
    return (f"{g['slug']:<20} {g['status']:<9} intake {g['intake']:<8} {g['source']:<4} "
            f"project {g['project']}")


def cmd_list(ctx) -> int:
    rows = ctx.client("viewer").get("/api/goals", status=ctx.args.status or "")["goals"]
    ctx.out(rows, "\n".join(_line(g) for g in rows) or "no goals")
    return EXIT_OK


def cmd_show(ctx) -> int:
    g = ctx.client("viewer").get(f"/api/goals/{ctx.args.id}")
    lim = g["limits"]
    lines = [_line(g), f"  text: {' '.join(g['spec']['goal']['text'].split())[:300]}",
             f"  sha256 {g['spec_sha256']}  limits: " + ", ".join(
                 f"{k} {v}" for k, v in lim.items() if k == "max_attempts" or v not in (0, "0"))]
    lines += [f"  job {j['display_id']} {j['status']:<17} {j['type']:<8} {j['title']}"
              for j in g.get("jobs", [])]
    ctx.out(g, "\n".join(lines))
    return EXIT_OK


def _status(verb: str):
    def cmd(ctx) -> int:
        res = ctx.client(ctx.args.as_role or "owner").post(f"/api/goals/{ctx.args.id}/{verb}")
        ctx.out(res, f"goal {res['slug']} {res['status']}")
        return EXIT_OK
    return cmd


def no_chat(what: str) -> bool:
    """The factory's steps never run from the orchestrator chat (docs/LEVEL5.md 4.0 step 4)."""
    if in_chat():
        print(f"konstant: refused: {what} is the factory's step, not the orchestrator chat's "
              "(KONSTANT_CHAT_SESSION is set): the chat proposes the goal and the owner's yes "
              "files it; `konstant intake` runs outside the chat (the owner, or the factory "
              "loop), and its result comes back here", file=sys.stderr)
        return True
    return False


def cmd_intake(ctx) -> int:
    if _no_task("intake") or no_chat("intake"):
        return EXIT_FAIL
    import time

    from konstant.factory import intake, notify
    from konstant.gate import harness as harness_mod
    from konstant.gate import loop
    started = time.time()
    loop.install_signals(started, lambda m: print(m, file=sys.stderr, flush=True))
    try:
        return intake.run(ctx, ctx.args.goal, ctx.args.harness)
    except harness_mod.HarnessError as exc:
        print(f"konstant intake: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except loop.Killed as k:
        # a stopped intake is an escalation, never silence (found in the L5-3 live smoke: a
        # timed-out intake left the chat with nothing to report)
        import signal
        name = signal.Signals(k.sig).name
        notify.emit(ctx.cfg, "BLOCKED", ctx.args.goal,
                    reason=f"intake stopped by {name} after {int(time.time() - started)}s; "
                    "`konstant goal show` says how far it got")
        try:
            ctx.client("factory").post(f"/api/goals/{ctx.args.goal}/intake", {"state": "refused"})
        except Exception:   # noqa: BLE001 - filing already reached `filed`: that state is final
            pass
        return 128 + int(k.sig)


def cmd_chat_turn(ctx) -> int:
    if _no_task("chat turn"):
        return EXIT_FAIL
    from konstant.factory import chat
    text = sys.stdin.read() if ctx.args.text == ["-"] else " ".join(ctx.args.text)
    try:
        res = chat.turn(ctx.cfg, ctx.client(), ctx.args.session, text)
    except ValueError as exc:
        print(f"konstant: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps(res, indent=2))
    return EXIT_OK


def register(sub, leaf) -> None:
    g = sub.add_parser("goal", help="level-5 goals: what the owner wants and its limits")
    gs = g.add_subparsers(dest="goal_cmd", metavar="VERB")
    gs.required = True
    p = gs.add_parser("add", parents=[leaf], help="file a goal file (owner), or propose one from "
                      "the owner's chat (--from-chat)")
    p.add_argument("file", help="the goal TOML file, or - for stdin")
    p.add_argument("--from-chat", action="store_true", help="a proposal from the orchestrator "
                   "chat: filed when the owner's next message in --session is a yes")
    p.add_argument("--session", help="the chat session id (default $KONSTANT_CHAT_SESSION)")
    p.set_defaults(func=cmd_add)
    p = gs.add_parser("list", parents=[leaf], help="goals with status, intake state, source")
    p.add_argument("--status", help="filter: proposed,active,paused,done,stopped,withdrawn")
    p.set_defaults(func=cmd_list)
    p = gs.add_parser("show", parents=[leaf], help="one goal: spec, limits, its jobs")
    p.add_argument("id")
    p.set_defaults(func=cmd_show)
    for verb, help_ in (("pause", "pause an active goal (owner)"),
                        ("resume", "resume a paused goal (owner)"),
                        ("cancel", "stop a goal for good (owner)")):
        p = gs.add_parser(verb, parents=[leaf], help=help_)
        p.add_argument("id")
        p.set_defaults(func=_status(verb))
    p = sub.add_parser("intake", parents=[leaf], help="turn a goal into jobs: planner, DoD "
                       "review, filing, approval, scenario writer (level 5)")
    p.add_argument("goal", help="the goal id")
    p.add_argument("--harness", help="an adapter name or an argv template for the intake phases "
                   "and the scenario writer (default: [harness] / [holdout] writer_harness)")
    p.set_defaults(func=cmd_intake)
    c = sub.add_parser("chat", help="the orchestrator chat as intake (the dsh plugin's seam)")
    cs = c.add_subparsers(dest="chat_cmd", metavar="VERB")
    cs.required = True
    p = cs.add_parser("turn", parents=[leaf], help="one owner message: confirm/withdraw this "
                      "session's goal proposal, new escalations, the intake block (JSON)")
    p.add_argument("--session", required=True, help="the chat session id")
    p.add_argument("text", nargs="+", help="the owner's message, or - for stdin")
    p.set_defaults(func=cmd_chat_turn)
