"""`konstant holdout add|list|check|show` (docs/LEVEL5.md 3.2).

add    lint + negative control + commitment; MOVES each source file into the sealed store
       (a source inside the workspace is refused). Acts as owner. Exit 0 sealed, 1 refused
       (one reason per line: MALFORMED, TRIVIAL, TEST RUNNER, NOT HELD OUT, HINT LEAKS,
       TOO FEW, NO PROOF, VACUOUS, REGRESSION FAILS, ...), 2 no jail / setup.
list   ids, kinds, commitments, states (no content; any token reads).
check  the commitment and parse of each sealed file; --control re-runs the negative control on
       the project's current HEAD. Prints ids and statuses only. Exit 1 when any is not ok.
show   one scenario's file, read from the store directly (no board route serves content).
add, check and show are refused inside a task run (KONSTANT_IN_TASK=1): a phase never handles
holdout content.
"""
from __future__ import annotations

import sys

from konstant.cli.main import EXIT_FAIL, EXIT_OK, EXIT_USAGE
from konstant.client import in_task
from konstant.holdout import store


def _refuse_in_task(verb: str) -> bool:
    if in_task():
        print(f"konstant: refused: holdout {verb} is not available inside a task run "
              "(KONSTANT_IN_TASK=1): holdout content never reaches a phase", file=sys.stderr)
        return True
    return False


def cmd_add(ctx) -> int:
    if _refuse_in_task("add"):
        return EXIT_FAIL
    try:
        rows = store.seal(ctx.cfg, ctx.client(ctx.args.as_role or "owner"), ctx.args.id,
                          ctx.args.file)
    except store.SealRefused as exc:
        for line in exc.lines:
            print(line, file=sys.stderr)
        return exc.code
    ctx.out({"job": ctx.args.id, "sealed": rows},
            "\n".join(f"sealed {r['hid']} ({r['kind']}) sha256 {r['sha256']}" for r in rows))
    return EXIT_OK


def cmd_list(ctx) -> int:
    res = store.rows(ctx.client("viewer"), ctx.args.id)
    lines = [f"job {res['job']}: {res['sealed']} sealed of {res['count']} "
             f"(min_per_job {res['min_per_job']})"]
    lines += [f"  {r['hid']:<4} {r['kind']:<10} {r['state']:<8} set {r['generation']} "
              f"{r['sha256']} sealed {r['sealed_at']} by {r['author_label']}"
              for r in res["holdouts"]]
    ctx.out(res, "\n".join(lines))
    return EXIT_OK


def cmd_check(ctx) -> int:
    if _refuse_in_task("check"):
        return EXIT_FAIL
    try:
        rows = store.check(ctx.cfg, ctx.client("viewer"), ctx.args.id, ctx.args.control)
    except store.SealRefused as exc:
        for line in exc.lines:
            print(line, file=sys.stderr)
        return exc.code
    except Exception as exc:          # noqa: BLE001 - a check that cannot run is not a pass
        from konstant.verify.holdout import HoldoutError
        if not isinstance(exc, HoldoutError):
            raise
        print(f"konstant: {exc}", file=sys.stderr)
        return EXIT_USAGE
    ctx.out({"job": ctx.args.id, "holdouts": [{"hid": h, "status": s} for h, s in rows]},
            "\n".join(f"{h}: {s}" for h, s in rows) or "no holdout")
    return EXIT_OK if all(s in ("ok", "burned", "retired") for _h, s in rows) else EXIT_FAIL


def cmd_show(ctx) -> int:
    if _refuse_in_task("show"):
        return EXIT_FAIL
    job = ctx.client("viewer").get(f"/api/jobs/{ctx.args.id}")
    try:
        data = store.read(ctx.cfg, job["id"], ctx.args.hid)
    except OSError:
        print(f"konstant: job {job['display_id']} has no readable holdout {ctx.args.hid}",
              file=sys.stderr)
        return EXIT_USAGE
    sys.stdout.write(data.decode("utf-8", "replace"))
    return EXIT_OK


def register(sub, leaf) -> None:
    h = sub.add_parser("holdout", help="sealed holdout scenarios of a job (run only by verify)")
    hs = h.add_subparsers(dest="holdout_cmd", metavar="VERB")
    hs.required = True
    p = hs.add_parser("add", parents=[leaf], help="lint, control and seal scenario files "
                      "(moves them into the store; owner)")
    p.add_argument("id", help="job id or display id")
    p.add_argument("--file", action="append", required=True, metavar="FILE",
                   help="a scenario file outside the workspace (repeat for a set)")
    p.set_defaults(func=cmd_add)
    p = hs.add_parser("list", parents=[leaf], help="ids, kinds, commitments and states")
    p.add_argument("id")
    p.set_defaults(func=cmd_list)
    p = hs.add_parser("check", parents=[leaf], help="commitment + parse of each sealed file")
    p.add_argument("id")
    p.add_argument("--control", action="store_true",
                   help="also re-run the negative control on the project's HEAD")
    p.set_defaults(func=cmd_check)
    p = hs.add_parser("show", parents=[leaf], help="print one sealed scenario (never in a task)")
    p.add_argument("id")
    p.add_argument("hid", help="H<n>")
    p.set_defaults(func=cmd_show)
