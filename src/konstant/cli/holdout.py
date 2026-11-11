"""`konstant holdout add|list|check|show` (docs/LEVEL5.md 3.2).

add    lint + negative control + commitment; MOVES each source file into the sealed store
       (a source inside the workspace is refused). Acts as owner. Exit 0 sealed, 1 refused
       (one reason per line: MALFORMED, TRIVIAL, TEST RUNNER, NOT HELD OUT, HINT LEAKS,
       TOO FEW, NO PROOF, VACUOUS, REGRESSION FAILS, ...), 2 no jail / setup.
list   ids, kinds, commitments, states (no content; any token reads).
check  the commitment and parse of each sealed file; --control re-runs the negative control on
       the project's current HEAD. Prints ids and statuses only. Exit 1 when any is not ok.
show   one scenario's file, read from the store directly (no board route serves content).
lint   the scenario writer's pre-check of its OWN drafts (`--draft FILE|DIR`, DIR = every
       *.scenario in it, linted as one set): the same lint as `add`, each reason naming what
       tripped it. No board, no store: a file in a sealed store other than a `drafts/` dir is
       refused, and the negative control is not run. The held-out rule uses the job context
       konstant writes next to the drafts (holdout/draft.py CONTEXT) or `--context`. Exit 0 ok,
       1 refused, 2 unreadable. Allowed inside a task run: it reads only the file it is given.
new    a scenario skeleton (`--kind proof|regression`, `--regex`) with every value to write as a
       `<FILL: ...>` placeholder the lint refuses; to stdout or `--out FILE` (never overwrites).
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


def cmd_author(ctx) -> int:
    """The scenario writer for one job (docs/LEVEL5.md 3.4): seals as the scenario identity."""
    from konstant.cli.goal import no_chat
    if _refuse_in_task("author") or no_chat("holdout author"):
        return EXIT_FAIL
    from konstant import catalog as catalog_mod
    from konstant.holdout import author
    cfg = ctx.cfg
    viewer = ctx.client("viewer")
    job = viewer.get(f"/api/jobs/{ctx.args.id}")
    goal_text = ""
    if job.get("goal"):
        goal_text = viewer.get(f"/api/goals/{job['goal']}")["spec"]["goal"]["text"]
    from konstant.verify.verifier import project_dir
    target = project_dir(cfg, viewer.get("/api/projects")["projects"], job["project"])
    cat = catalog_mod.load(catalog_mod.find_root(cfg.home, cfg.data["catalog"]["path"]),
                           check_files=True)
    try:
        res = author.author(cfg, cat, job, goal_text or job["title"], target,
                            ctx.client("scenario"), cfg.data["holdout"]["min_per_job"],
                            ctx.args.harness, log=lambda m: print(m, file=sys.stderr))
    except author.AuthorRefused as exc:
        print(f"konstant: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if "blocked" in res:
        print(res["blocked"], file=sys.stderr)
        return 4
    ctx.out({"job": job["id"], **res}, "\n".join(
        f"sealed {r['hid']} ({r['kind']}) sha256 {r['sha256']} by {r['author_label']}"
        for r in res["sealed"]))
    return EXIT_OK


def cmd_lint(ctx) -> int:
    """The draft pre-check (holdout/draft.py): never the board, never the sealed store."""
    from pathlib import Path
    from konstant.holdout import draft
    a = ctx.args
    try:
        files = draft.expand(a.draft, ctx.cfg.home)
    except draft.DraftRefused as exc:
        print(f"konstant: refused: {exc}", file=sys.stderr)
        return EXIT_USAGE
    first = Path(a.draft[0])
    cpath = Path(a.context) if a.context else \
        (Path(files[0]).parent if files else first if first.is_dir() else first.parent) \
        / draft.CONTEXT
    if not draft.allowed(str(cpath), draft.sealed_roots(ctx.cfg.home)):
        print(f"konstant: refused: {cpath} lies in a sealed store", file=sys.stderr)
        return EXIT_USAGE
    res = draft.check(files, draft.read_context(cpath))
    ctx.out(res, draft.report(res))
    return EXIT_OK if res["ok"] else EXIT_FAIL


def cmd_new(ctx) -> int:
    import os
    from konstant.holdout import draft
    text = draft.skeleton(ctx.args.kind, ctx.args.regex)
    if not ctx.args.out:
        sys.stdout.write(text)
        return EXIT_OK
    try:
        fd = os.open(ctx.args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        print(f"konstant: {ctx.args.out}: {exc.strerror} (holdout new never overwrites a file)",
              file=sys.stderr)
        return EXIT_USAGE
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote a {ctx.args.kind} skeleton to {ctx.args.out}: replace every <FILL: ...> value")
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
    p = hs.add_parser("author", parents=[leaf], help="run the scenario writer for a job and "
                      "seal its drafts (the scenario identity; exit 4 refused [holdout] "
                      "author_attempts times)")
    p.add_argument("id", help="job id or display id")
    p.add_argument("--harness", help="an adapter name for the scenario writer (default "
                   "[holdout] writer_harness, else [harness])")
    p.set_defaults(func=cmd_author)
    p = hs.add_parser("lint", parents=[leaf], help="pre-check scenario drafts (the scenario "
                      "writer's own; no board, no store; same rules as add)")
    p.add_argument("--draft", action="append", required=True, metavar="FILE|DIR",
                   help="a draft file, or a dir: every *.scenario in it as one set (repeatable)")
    p.add_argument("--context", metavar="FILE", help="the job context (brief, DoD, set size; "
                   "default: the .konstant-draft.json beside the drafts)")
    p.set_defaults(func=cmd_lint)
    p = hs.add_parser("new", parents=[leaf], help="write a scenario skeleton to fill in")
    p.add_argument("--kind", required=True, choices=("proof", "regression"))
    p.add_argument("--regex", action="store_true", help="EXPECT_RE instead of EXPECT_OUT")
    p.add_argument("--out", metavar="FILE", help="write it here (never overwrites; default "
                   "stdout)")
    p.set_defaults(func=cmd_new)
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
