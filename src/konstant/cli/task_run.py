"""`konstant task run`: wire the CLI to the phase runner and the DoD loop (gate/loop.py).

A small task runs in the project dir when one is given and refuses a `--job` (a job is never
closed by an ungated run; force a type with --type; REVIEW F-26). One run per project at a time:
a run holds `var/locks/<project>.lock` (flock) for its whole life, a second run on the same
project exits 2 (REVIEW F-28: runs on one project would pin each other's drift).
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import shlex
import shutil
import sys
import time
from pathlib import Path

from konstant.cli.main import EXIT_USAGE
from konstant.gate import check as check_mod
from konstant.gate import harness as harness_mod
from konstant.gate import loop
from konstant.gate.record import new_run_dir
from konstant.gate.runner import PhaseRunner


def err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def cli_template(template: str) -> str:
    """A `--harness` typed on the command line: a relative path in it that exists from the
    caller's cwd is made absolute (the harness itself runs in the project dir, DESIGN §9)."""
    out = []
    for tok in shlex.split(template):
        if ("/" in tok and "{" not in tok and not tok.startswith("-") and not os.path.isabs(tok)
                and os.path.exists(tok)):
            tok = os.path.abspath(tok)
        out.append(tok)
    return shlex.join(out)


def _harness(ctx, cat=None) -> harness_mod.HarnessSet:
    """The phase harnesses from [harness] (docs/HARNESSES.md); `--harness NAME` (an adapter:
    claude, codex, gemini, dsh) or `--harness CMD` (an argv template) replaces them all."""
    from konstant import harnesses
    h = ctx.cfg.data["harness"]
    a = ctx.args.harness
    over = (a if a in harnesses.ADAPTERS else cli_template(a)) if a else None
    return harness_mod.HarnessSet(h, ctx.cfg.home, cat, ctx.cfg.data["permissions"]["allow"],
                                  override=over, jail=bool(ctx.cfg.data["gate"]["jail"]))


def _small(ctx, task: str, why: str) -> int:
    from konstant.cli.task import _project_path
    if ctx.args.job:
        err(f"konstant task: the task classified small ({why}) but --job {ctx.args.job} binds it "
            "to a job, and an ungated run never closes a job: re-run with --type <type>")
        return EXIT_USAGE
    cwd = _project_path(ctx, ctx.args.project) if ctx.args.project else ctx.cfg.home
    run_dir, _s, _g = new_run_dir(ctx.cfg.home, task)
    err(f"konstant task: small ({why}) - one harness run in {cwd}, no gate; log "
        f"{run_dir}/phases/")
    res = _harness(ctx).run(task, agent="orchestrator", cwd=Path(cwd), run_dir=run_dir,
                            label="small")
    return res.rc


def holdout_confinement(ctx, cat) -> str | None:
    """Why a job with sealed holdouts may not run here (docs/LEVEL5.md 2.1): every phase must run
    inside konstant's jail, whatever the harness; nothing falls back to "procedural"."""
    from konstant.verify.holdout import UNCONFINED, confined
    why = confined(ctx.cfg)
    if why:
        return why
    loose = _harness(ctx, cat).unconfined()
    if loose:
        return (f"{UNCONFINED}: the harness(es) {', '.join(loose)} do not run their phases in "
                "konstant's jail (before L5-2 only dsh does): run this job with --harness dsh")
    return None


def project_lock(home: Path, project):
    """An open, flock-ed file for the project, or None when another run holds it."""
    if not project:
        return True
    d = Path(home) / "var" / "locks"
    d.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(os.path.realpath(str(project)).encode()).hexdigest()[:16]
    fh = open(d / f"project-{key}.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    fh.write(f"{os.getpid()} {project}\n")
    fh.flush()
    return fh


def run(ctx, task: str, prepare) -> int:
    started = time.time()
    loop.install_signals(started, err)
    try:
        return _run(ctx, task, prepare)
    except harness_mod.HarnessError as exc:
        err(f"konstant task: {exc}")
        return EXIT_USAGE
    except loop.Killed as k:
        return 128 + int(k.sig)


def _run(ctx, task: str, prepare) -> int:
    a, cfg = ctx.args, ctx.cfg
    cat, t, why, rec, run_dir = prepare(ctx, task, "runner")
    if t is None:
        return _small(ctx, task, why)
    if "holdouts" in rec:
        why = holdout_confinement(ctx, cat)
        if why:
            shutil.rmtree(run_dir, ignore_errors=True)
            err(f"konstant task: {why}")
            return EXIT_USAGE
    lock = project_lock(cfg.home, rec.get("project"))
    if lock is None:
        shutil.rmtree(run_dir, ignore_errors=True)
        err(f"konstant task: another task run is active on project {rec['project']}: one run per "
            "project at a time (a later run would change the state an earlier one pinned)")
        return EXIT_USAGE
    ctx._project_lock = lock          # held until this process exits
    gate = cfg.data["gate"]
    max_cycles = a.max_cycles or gate["max_cycles"]
    max_resumes = a.max_resumes if a.max_resumes is not None else gate["max_resumes"]
    harness = _harness(ctx, cat)
    harness.check()                                                          # fail fast
    err(f"konstant task: [type:{t}] ({why}) run {run_dir}")
    client = ctx.client() if rec.get("job") else None
    if client is not None:
        job = client.get(f"/api/jobs/{rec['job']}")
        if job["status"] in ("queued", "blocked"):
            client.post(f"/api/jobs/{rec['job']}/claim")
            err(f"konstant task: claimed job {rec['job']}")
    pr = PhaseRunner(rec, cat, harness, run_dir=Path(run_dir),
                     max_parallel=cfg.data["harness"]["max_parallel"],
                     acceptance=rec.get("acceptance", ""), log=err, isolate=True)
    pr.run_all(max_cycles)
    pr.closeout()
    board = check_mod.BoardView(ctx.client("viewer")) if rec.get("job") else None
    code, lines = loop.dod_loop(pr, board, max_resumes, err)
    for ln in lines:
        print(ln)
    names = {0: "MET", 3: "UNMET", 4: "BLOCKED"}
    err(f"konstant task: {names.get(code, 'CHECK-ERROR')} - run {run_dir} "
        f"(`konstant task check {run_dir}`)")
    if client is not None:
        stamp = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))  # noqa: E731
        client.post(f"/api/jobs/{rec['job']}/runs",
                    {"run_dir": str(run_dir), "type": t, "started_at": stamp(rec["start"]),
                     "finished_at": stamp(time.time()), "result": names.get(code, "ERROR")})
    if code == 0 and rec.get("job"):
        return loop.close_and_verify(rec, client, cfg, err)
    return code
