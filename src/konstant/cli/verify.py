"""`konstant verify ID [--dry-run] [--no-rerun]` and `konstant verify --pending` (DESIGN §7).

Exit 0 PASS, 3 FAIL, 4 BLOCKED, 2 job not found or wrong state, 1 refusal. The verdict is posted
with the verifier token (or the owner's when `--as owner` is given); --dry-run only reads and
uses the viewer token, so it works anywhere, including inside a task run.
"""
from __future__ import annotations

import sys

from konstant.cli.main import EXIT_FAIL, EXIT_OK, EXIT_USAGE
from konstant.client import ClientError
from konstant.verify.verifier import PENDING, NotVerifiable, verify_job

EXIT_VERDICT = {"PASS": EXIT_OK, "FAIL": 3, "BLOCKED": 4}


def _human(res: dict) -> str:
    lines = [f"JOB={res['display_id']} verdict={res['verdict']}"
             + (" (dry run, nothing written)" if res["dry_run"] else "")]
    lines += [f"  {r}" for r in res["reasons"]]
    for p in res["probes"]:
        state = "error" if p["error"] else "match" if p["matched"] else "NO MATCH"
        lines.append(f"  probe [{p['source']}] {state}: {p['line']}")
    rr = res["rerun"]
    if rr:
        lines.append("  re-run: " + (f"exit {rr['exit']}" if rr["ran"] else str(rr["skipped"])))
    return "\n".join(lines)


def _role(ctx) -> str:
    asked = ctx.args.as_role
    return asked if asked == "owner" else "verifier"


def _one(ctx, ref, dry: bool):
    client = ctx.client("viewer" if dry else _role(ctx))
    return verify_job(client, ctx.cfg, ref, dry_run=dry, rerun=not ctx.args.no_rerun)


def cmd_verify(ctx) -> int:
    a = ctx.args
    if a.pending == bool(a.id):
        print("konstant: give a job id or --pending (not both)", file=sys.stderr)
        return EXIT_USAGE
    if not a.pending:
        try:
            res = _one(ctx, a.id, a.dry_run)
        except NotVerifiable as exc:
            print(f"konstant: {exc}", file=sys.stderr)
            return EXIT_USAGE
        ctx.out(res, _human(res))
        return EXIT_VERDICT[res["verdict"]]
    jobs = ctx.client("viewer").get("/api/jobs", status=PENDING)["jobs"]
    results, errors = [], 0
    for j in jobs:
        try:
            results.append(_one(ctx, j["id"], a.dry_run))
        except (NotVerifiable, ClientError) as exc:
            print(f"konstant: job {j['display_id']}: {getattr(exc, 'message', str(exc))}",
                  file=sys.stderr)
            errors += 1
    ctx.out(results, "\n".join(_human(r) for r in results) or "no job awaits verification")
    codes = {EXIT_VERDICT[r["verdict"]] for r in results}
    return 3 if 3 in codes else 4 if 4 in codes else EXIT_FAIL if errors else EXIT_OK


def register(sub, leaf) -> None:
    p = sub.add_parser("verify", parents=[leaf], help="verify a completed job (probes + re-run)")
    p.add_argument("id", nargs="?", help="job id or display id")
    p.add_argument("--pending", action="store_true", help="verify every completed_unverified job")
    p.add_argument("--dry-run", action="store_true", help="print the result, write nothing")
    p.add_argument("--no-rerun", action="store_true", help="skip the verify_cmd re-run")
    p.set_defaults(func=cmd_verify)
