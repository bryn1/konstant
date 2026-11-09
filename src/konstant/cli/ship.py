"""`konstant ship JOB`, `konstant ship list`, `konstant factory status|resume-shipping`
(docs/LEVEL5.md 5, factory/ship.py).

ship JOB              ship the exact commit the verifier passed (as the factory identity): the
                      guard on both sides, the target move, the post-ship checks, the rollback.
                      exit 0 shipped, 1 refused (nothing moved), 3 rolled back, 4 rollback failed
                      (shipping halted), 2 not found
  --dry-run           print the decision and every rule; moves nothing, records nothing
  --approve-decision  (--as owner) the owner decides an owner-decision refusal (5.4) for the
                      verified commit, then the factory ships it
ship list             every ship with its state
factory status        whether shipping is open or halted, and the ships so far
factory resume-shipping   (owner) lift the halt a failed rollback set
All of it is refused inside a task run and in the orchestrator chat: phases and the chat never
ship (their tokens could not either).
"""
from __future__ import annotations

import sys

from konstant.cli.main import EXIT_FAIL, EXIT_OK, EXIT_USAGE
from konstant.client import ClientError, in_chat, in_task


def _refused_here(what: str) -> bool:
    if in_task():
        print(f"konstant: refused: {what} is not available inside a task run "
              "(KONSTANT_IN_TASK=1): only the factory ships", file=sys.stderr)
        return True
    if in_chat():
        print(f"konstant: refused: {what} is the factory's step, not the orchestrator chat's "
              "(KONSTANT_CHAT_SESSION is set)", file=sys.stderr)
        return True
    return False


def _human(res: dict) -> str:
    lines = [f"konstant ship: job {res.get('display_id', res.get('job'))} -> "
             f"{res.get('target')} {res.get('branch')}: {res.get('decision')}"]
    for r in res.get("rules", []):
        side = "board" if r.get("side") == "board" else "code "
        lines.append(f"  [{side}] {'ok  ' if r['ok'] else 'FAIL'} {r['rule']}: {r['reason']}")
    for k in ("ship", "state", "tip", "rollback", "follow_up"):
        if res.get(k) is not None:
            lines.append(f"  {k}: {res[k]}")
    for c in (res.get("post") or {}).get("checks", []):
        lines.append(f"  post {'ok  ' if c['ok'] else 'FAIL'} {c['check']}: {c['reason']}")
    return "\n".join(lines)


def cmd_ship(ctx) -> int:
    a = ctx.args
    if _refused_here("ship"):
        return EXIT_FAIL
    from konstant.factory import ship
    cfg = ctx.cfg
    factory = ctx.client("factory")
    if a.dry_run:
        res = ship.dry_run(cfg, factory, a.job)
        ctx.out(res, _human(res))
        return EXIT_OK if res["decision"] == "ship" else EXIT_FAIL
    if a.approve_decision:
        if a.as_role != "owner":
            print("konstant: refused: --approve-decision is the owner's decision "
                  "(`konstant --as owner ship JOB --approve-decision`)", file=sys.stderr)
            return EXIT_FAIL
        job = factory.get(f"/api/jobs/{a.job}")
        commit = ((job.get("evidence") or {}).get("commit") or "").strip()
        ctx.client("owner").post(f"/api/jobs/{a.job}/ship-decision",
                                 {"commit": commit, "reason": "owner decision at ship time"})
    rc, res = ship.ship(cfg, factory, a.job)
    if rc == ship.EXIT_REFUSED:
        bad = [r for r in res.get("rules", []) if not r["ok"]]
        why = bad[0]["reason"] if bad else res.get("reason", "refused")
        if not why.startswith(("refused", "target moved", "DECISION", "target refused")):
            why = f"refused: {why}"
        print(why, file=sys.stderr)
    ctx.out(res, _human(res))
    return rc


def cmd_list(ctx) -> int:
    rows = ctx.client("viewer").get("/api/ships")["ships"]
    ctx.out(rows, "\n".join(f"ship {s['id']:<4} job {s['display_id']:<10} {s['state']:<16} "
                            f"{s['target']} {s['branch'] or ''} {s['commit_sha'][:12]}"
                            for s in rows) or "no ships")
    return EXIT_OK


def cmd_status(ctx) -> int:
    c = ctx.client("viewer")
    try:
        sh = c.get("/api/factory/shipping")
        ships = c.get("/api/ships")["ships"]
    except ClientError as exc:
        print(f"konstant: {exc.message}", file=sys.stderr)
        return EXIT_USAGE
    states = {}
    for s in ships:
        states[s["state"]] = states.get(s["state"], 0) + 1
    res = {**sh, "ships": states}
    ctx.out(res, f"shipping {sh['shipping']}" + (f" since {sh['since']}: {sh['reason']}"
                                                 if sh["shipping"] == "halted" else "")
            + ("; ships: " + ", ".join(f"{k} {v}" for k, v in sorted(states.items()))
               if states else ""))
    return EXIT_OK


def cmd_resume(ctx) -> int:
    if _refused_here("factory resume-shipping"):
        return EXIT_FAIL
    res = ctx.client(ctx.args.as_role or "owner").post(
        "/api/factory/shipping", {"action": "resume", "reason": "resumed by the owner"})
    ctx.out(res, f"shipping {res['shipping']}")
    return EXIT_OK


def register(sub, leaf) -> None:
    s = sub.add_parser("ship", parents=[leaf], help="level 5: ship a verified job's exact commit, "
                       "check the shipped state, roll it back on failure; `ship list`: the ships")
    s.add_argument("job", metavar="JOB|list", help="the job to ship, or `list` for every ship")
    s.add_argument("--dry-run", action="store_true", help="print the decision and every guard "
                   "rule; move nothing")
    s.add_argument("--approve-decision", action="store_true", help="(--as owner) ship past an "
                   "owner decision (5.4) for the verified commit")
    s.set_defaults(func=_dispatch)
    f = sub.add_parser("factory", help="level 5: the factory's shipping state")
    fs = f.add_subparsers(dest="factory_cmd", metavar="VERB")
    fs.required = True
    p = fs.add_parser("status", parents=[leaf], help="shipping open or halted, ships by state")
    p.set_defaults(func=cmd_status)
    p = fs.add_parser("resume-shipping", parents=[leaf], help="(owner) lift the halt a failed "
                      "rollback set")
    p.set_defaults(func=cmd_resume)


def _dispatch(ctx) -> int:
    if ctx.args.job == "list":
        return cmd_list(ctx)
    return cmd_ship(ctx)
