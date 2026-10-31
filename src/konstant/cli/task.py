"""`konstant task classify|gate|check|judge|run` (DESIGN §6, §12)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from konstant import catalog as catalog_mod
from konstant.cli.main import EXIT_FAIL, EXIT_OK, EXIT_USAGE, warn
from konstant.client import ClientError
from konstant.gate import check as check_mod
from konstant.gate import classify as classify_mod
from konstant.gate import record as record_mod
from konstant.gate import render
from konstant.gate.rules import judged


def _task_text(ctx) -> str:
    text = " ".join(ctx.args.text)
    return sys.stdin.read() if text.strip() == "-" else text


def _catalog(ctx):
    try:
        home = ctx.cfg.home
        configured = ctx.cfg.data["catalog"]["path"]
    except Exception:  # classify works outside a workspace (source-tree catalog)
        home, configured = None, ""
    return catalog_mod.load(catalog_mod.find_root(home, configured))


def cmd_classify(ctx) -> int:
    cat = _catalog(ctx)
    t, why = classify_mod.classify(_task_text(ctx), cat)
    ctx.out({"type": t or "small", "why": why}, f"{t or 'small'} why={why}")
    return EXIT_OK


def _project_path(ctx, slug: str):
    if not slug:
        return None
    try:
        rows = ctx.client("viewer").get("/api/projects")["projects"]
    except ClientError as exc:
        if exc.status:
            raise
        guess = ctx.cfg.home / "projects" / slug
        if guess.is_dir():
            warn(f"board unreachable; using {guess} for project {slug}")
            return guess
        raise
    for r in rows:
        if r["slug"] == slug:
            return ctx.cfg.resolve(r["path"])
    raise ClientError(f"project {slug!r} not found", 404)


def _job(ctx, job):
    """The job dict, or None when the board cannot be reached (a reachable 404 -> exit 2)."""
    if not job:
        return None
    try:
        j = ctx.client("viewer").get(f"/api/jobs/{job}")
    except ClientError as exc:
        if exc.status:
            raise
        warn(f"board unreachable: job {job} not checked ({exc.message})")
        return None
    if j["status"] in ("verified", "reviewed", "cancelled"):
        raise ClientError(f"job {job} is {j['status']}: a run needs an open job", 409)
    return j


def prepare(ctx, task: str, mode: str):
    """Classify + run record. Returns (catalog, type, why, rec, run_dir) or a small result."""
    a = ctx.args
    cat = _catalog(ctx)
    t, why = classify_mod.classify(task, cat)
    if a.type:
        if a.type not in cat.types:
            raise ClientError(f"unknown --type {a.type!r}; known: {', '.join(cat.type_names())}", 404)
        t, why = a.type, "flag"
    if t is None:
        return cat, None, why, None, None
    from konstant.cli import task_session
    slug = a.project or (task_session.project_for_cwd(ctx, getattr(a, "cwd", None) or "")
                         if getattr(a, "cwd", None) else None)
    ref, how = task_session.resolve_job(ctx, task, t, slug or "")
    job = _job(ctx, ref)
    project = _project_path(ctx, a.project or (job or {}).get("project") or slug or "")
    run_dir, stamp, slug = record_mod.new_run_dir(ctx.cfg.home, task)
    out = Path(a.out).resolve() if a.out else record_mod.default_out(project, run_dir, stamp, slug)
    rec = record_mod.build(cat, task, t, why, run_dir=run_dir, out=out, project=project,
                           workspace=ctx.cfg.home, job=int(job["id"]) if job else None, mode=mode,
                           gate_cfg=ctx.cfg.data["gate"])
    if job:
        rec["acceptance"] = job.get("acceptance") or ""
        rec["job_display"] = job.get("display_id") or str(job["id"])
        rec["job_bound_by"] = how
    record_mod.write(run_dir, rec)
    return cat, t, why, rec, run_dir


def cmd_gate(ctx) -> int:
    task = _task_text(ctx)
    cat, t, why, rec, run_dir = prepare(ctx, task, "interactive")
    if t is None:
        ctx.out({"type": "small", "why": why}, task)
        return EXIT_OK
    blk = render.block(rec, cat, harness=ctx.args.harness or _session_harness(ctx))
    if ctx.args.json:
        ctx.out({"type": t, "why": why, "run_dir": str(run_dir), "out": rec["out"],
                 "block": blk, "block_chars": render.block_len(blk, rec), "job": rec["job"],
                 "job_display": rec.get("job_display"), "project": rec["project"]})
    else:
        print(blk + "\n" + task)
        print(f"konstant task: run record {run_dir}/record.json", file=sys.stderr)
    return EXIT_OK


def _session_harness(ctx) -> str:
    """The harness an orchestrating session most likely runs in: claude when configured."""
    try:
        from konstant import harnesses
        names = harnesses.configured(ctx.cfg.data["harness"])
    except Exception:
        return "claude"
    return "claude" if "claude" in names else names[0]


def _resolve_run(ctx, ref: str) -> Path:
    p = Path(ref)
    if p.exists():
        return p
    try:
        cand = ctx.cfg.home / "var" / "runs" / ref
    except Exception:
        return p
    return cand if cand.exists() else p


def _home(ctx):
    """The caller's workspace (KONSTANT_HOME / --config / cwd), or None outside one."""
    try:
        return ctx.cfg.home
    except Exception:
        return None


def board_view(ctx):
    try:
        return check_mod.BoardView(ctx.client("viewer"))
    except Exception:
        return None


def cmd_check(ctx) -> int:
    run = _resolve_run(ctx, ctx.args.run)
    board = None if ctx.args.offline else board_view(ctx)
    code, lines, warns, findings = check_mod.run_check(run, board, ctx.args.offline,
                                                       home=_home(ctx))
    for w in warns:
        print(f"konstant check: {w}", file=sys.stderr)
    if ctx.args.json:
        print(json.dumps(check_mod.as_json(code, findings), indent=2))
    elif lines:
        print("\n".join(lines))
    return code


def cmd_judge(ctx) -> int:
    a = ctx.args
    if a.run:
        try:
            rec = check_mod.load_run(_resolve_run(ctx, a.run), home=_home(ctx)).rec
        except check_mod.CheckUsage as exc:
            print(f"konstant: {exc}", file=sys.stderr)
            return EXIT_USAGE
    elif a.out:
        rec = {"out": str(Path(a.out).resolve()), "git_base": a.base or None,
               "project": str(Path(a.project).resolve()) if a.project else None}
    else:
        print("konstant: task judge needs --run RUN or --out OUT", file=sys.stderr)
        return EXIT_USAGE
    try:
        sha = judged.judge(rec)
    except judged.JudgeRefused as exc:
        print(f"konstant task judge: REFUSED - {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"# JUDGED: {sha}")
    return EXIT_OK


def cmd_run(ctx) -> int:
    from konstant.cli.task_run import run
    return run(ctx, _task_text(ctx), prepare)


def register(sub, leaf) -> None:
    t = sub.add_parser("task", help="task gate, phase runner, DoD check")
    ts = t.add_subparsers(dest="task_cmd", metavar="ACTION")
    ts.required = True

    def leafp(name, help_, func, text=True):
        p = ts.add_parser(name, parents=[leaf], help=help_)
        p.set_defaults(func=func)
        if text:
            p.add_argument("text", nargs="+", help="the task text, or - for stdin")
        return p

    leafp("classify", "classify a task: small or a type, and why", cmd_classify)
    for name, help_, func in (("gate", "print the gate block and write the run record", cmd_gate),
                              ("run", "run the phases and the DoD loop", cmd_run)):
        p = leafp(name, help_, func)
        p.add_argument("--job", help="the board job this run works on")
        p.add_argument("--project", help="project slug (default: the job's project)")
        p.add_argument("--type", help="force the task type")
        p.add_argument("--out", help="the OUT dir (default <project>/.audits/<stamp>-<slug>/out)")
        p.add_argument("--file-job", action="store_true",
                       help="file and claim a job for a typed task that names none (the task "
                       "text is the brief: it needs a DoD section)")
        p.add_argument("--session", help="bind the job to this session id (var/sessions.json): "
                       "its next typed task reuses the open job")
        p.add_argument("--cwd", help="the session's directory: the project whose path holds it "
                       "when --project and the job name none")
        if name == "run":
            p.add_argument("--harness", help="an adapter name (claude, codex, gemini, dsh) or an "
                           "argv template for every phase (default: [harness] in konstant.toml)")
            p.add_argument("--max-cycles", type=int, help="back-edge cap (default [gate])")
            p.add_argument("--max-resumes", type=int, help="DoD-loop resumes (default [gate])")
        else:
            p.add_argument("--harness", help="the harness the orchestrating session runs in "
                           "(where the gate block points for agent profiles; default claude "
                           "when configured)")
    p = leafp("check", "run the mechanical DoD check on a run", cmd_check, text=False)
    p.add_argument("run", help="run dir (or its record.json, or a name under var/runs)")
    p.add_argument("--offline", action="store_true", help="no board reads (rule verified skipped)")
    from konstant.cli.task_session import cmd_close
    p = leafp("close", "close-out of an interactive run: MET -> close the job -> konstant verify",
              cmd_close, text=False)
    p.add_argument("run", help="run dir (or its record.json, or a name under var/runs)")
    p = leafp("judge", "print the # JUDGED line for a run's deliverable state", cmd_judge, text=False)
    p.add_argument("--run", help="run dir (reads OUT, project and base from its record)")
    p.add_argument("--out", help="OUT dir (without a run record)")
    p.add_argument("--project", help="project dir (with --out)")
    p.add_argument("--base", help="git base commit (with --out)")
