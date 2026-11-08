"""`konstant task run`: wire the CLI to the phase runner and the DoD loop (gate/loop.py).

A small task runs in the project dir when one is given and refuses a `--job` (a job is never
closed by an ungated run; force a type with --type; REVIEW F-26). One run per project at a time:
a run holds `var/locks/<project>.lock` (flock) for its whole life, a second run on the same
project exits 2 (REVIEW F-28: runs on one project would pin each other's drift).

Factory mode (a job with sealed holdouts, docs/LEVEL5.md 2.1, 2.4): every phase runs in konstant's
jail on any harness (exit 2 `holdouts need a confined phase` when it cannot), the claim records
the job clone `<project>@<job>` on the board, and the run works in that clone (made here by
factory/clone.py from the target commit the board recorded); the target stays read-only.
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
from konstant.client import ClientError
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


def _harness(ctx, cat=None, factory: bool = False) -> harness_mod.HarnessSet:
    """The phase harnesses from [harness] (docs/HARNESSES.md); `--harness NAME` (an adapter:
    claude, codex, gemini, dsh) or `--harness CMD` (an argv template) replaces them all.
    `factory`: every phase confined in konstant's jail (docs/LEVEL5.md 2.1)."""
    from konstant import harnesses
    h = ctx.cfg.data["harness"]
    a = ctx.args.harness
    over = (a if a in harnesses.ADAPTERS else cli_template(a)) if a else None
    return harness_mod.HarnessSet(h, ctx.cfg.home, cat, ctx.cfg.data["permissions"]["allow"],
                                  override=over, jail=bool(ctx.cfg.data["gate"]["jail"]),
                                  factory=factory, conf=ctx.cfg.confinement())


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
    loose = _harness(ctx, cat, factory=True).unconfined()
    if loose:
        return (f"{UNCONFINED}: the harness(es) {', '.join(loose)} would not run their phases "
                "in konstant's jail")
    return None


def bind_clone(ctx, rec: dict, run_dir: Path) -> None:
    """Factory mode, after the claim: make (or keep) the job clone the board recorded and make it
    the run's project (docs/LEVEL5.md 2.4). The record's git base is the target commit the clone
    started from, so every round's diff, leak scan and evidence BASE= cover all of the job's work."""
    from konstant.factory import clone
    from konstant.gate import record as record_mod
    job = ctx.client("viewer").get(f"/api/jobs/{rec['job']}")
    if not job.get("workdir") or not job.get("workdir_base"):
        raise clone.CloneError(f"job {rec['job']} is claimed but the board recorded no job clone "
                               "(claimed before konstant L5-2): `job reopen` it, then run it again")
    path = ctx.cfg.resolve(job["workdir"])
    how = clone.create(rec["target"], path, job["workdir_base"])
    err(f"konstant task: job clone {path} ({how}, base {job['workdir_base'][:12]}); the target "
        f"{rec['target']} is read-only to every phase")
    rec.update(project=str(path.resolve()), git_top=str(path.resolve()),
               git_base=job["workdir_base"], workdir=job["workdir"])
    if not rec.pop("out_given", False):           # record.default_out, in the clone
        rec["out"] = str((path / ".audits" / Path(run_dir).name / "out").resolve())
    record_mod.write(run_dir, rec)


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
    factory = "holdouts" in rec
    if factory:
        refusal = holdout_confinement(ctx, cat)
        if refusal:
            shutil.rmtree(run_dir, ignore_errors=True)
            err(f"konstant task: {refusal}")
            return EXIT_USAGE
        return _run_factory(ctx, task, cat, t, why, rec, run_dir)
    lock = project_lock(cfg.home, rec.get("project"))
    if lock is None:
        shutil.rmtree(run_dir, ignore_errors=True)
        err(f"konstant task: another task run is active on project {rec['project']}: one run per "
            "project at a time (a later run would change the state an earlier one pinned)")
        return EXIT_USAGE
    ctx._project_lock = lock          # held until this process exits
    harness = _harness(ctx, cat)
    harness.check()                                                          # fail fast
    err(f"konstant task: [type:{t}] ({why}) tier {rec.get('tier', 'agent')} run {run_dir}")
    client = ctx.client() if rec.get("job") else None
    if client is not None:
        _claim(client, rec)
    return _phases(ctx, cat, t, rec, run_dir, harness, client)


def _claim(client, rec: dict) -> None:
    job = client.get(f"/api/jobs/{rec['job']}")
    if job["status"] in ("queued", "blocked"):
        client.post(f"/api/jobs/{rec['job']}/claim")
        err(f"konstant task: claimed job {rec['job']}")


def _run_factory(ctx, task: str, cat, t: str, why: str, rec: dict, run_dir) -> int:
    """A holdout job: every phase jailed, claim first (the board records the clone), then the
    clone becomes the run's project and its one-run lock (docs/LEVEL5.md 2.1, 2.4)."""
    from konstant.factory.clone import CloneError
    harness = _harness(ctx, cat, factory=True)
    harness.check()                                                          # fail fast
    client = ctx.client()
    try:
        _claim(client, rec)
        bind_clone(ctx, rec, Path(run_dir))
    except ClientError:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    except CloneError as exc:
        shutil.rmtree(run_dir, ignore_errors=True)
        err(f"konstant task: {exc}")
        return EXIT_USAGE
    lock = project_lock(ctx.cfg.home, rec["project"])
    if lock is None:
        err(f"konstant task: another task run is active on the job clone {rec['project']}")
        return EXIT_USAGE
    ctx._project_lock = lock
    err(f"konstant task: [type:{t}] ({why}) run {run_dir} (factory mode: every phase jailed)")
    return _phases(ctx, cat, t, rec, run_dir, harness, client)


def max_parallel(hcfg: dict) -> int:
    """[harness] max_parallel, never above the endpoint's real slots ([harness] max_concurrency
    when set): more concurrent phases than slots evict each other's prompt cache."""
    mp, mc = int(hcfg["max_parallel"]), int(hcfg.get("max_concurrency") or 0)
    return max(1, min(mp, mc) if mc else mp)


def research_step(ctx, cat, rec: dict, run_dir, override=None) -> None:
    """The intake card's research step (konstant/triage/research.py), run by code before any
    planning phase when the card says nothing similar was found: the closed researcher, whose
    parsed, cited summary (never its raw pages) every phase prompt then carries."""
    card = rec.get("card") or {}
    if not card.get("research_required"):
        return
    from konstant.gate import record as record_mod
    from konstant.triage import card as card_mod
    from konstant.triage import research
    try:
        client = ctx.client("researcher")
    except (ClientError, OSError):
        client = None
    res = research.run(ctx.cfg, cat, rec, card_mod.render(card), client=client,
                       override=override, log=err)
    rec["research"] = {"state": res["state"], "summary": res.get("summary") or "",
                       "memory": res.get("memory")}
    record_mod.write(run_dir, rec)


def _phases(ctx, cat, t: str, rec: dict, run_dir, harness, client) -> int:
    cfg, a = ctx.cfg, ctx.args
    gate = cfg.data["gate"]
    max_cycles = a.max_cycles or gate["max_cycles"]
    max_resumes = a.max_resumes if a.max_resumes is not None else gate["max_resumes"]
    tier = (rec.get("card") or {}).get("tier") or {}
    if tier.get("name") in ("fanout", "max"):
        err(f"konstant task: tier {tier['name']} ({tier['why']}): this runner works the task as "
            f"ONE typed run; the fan-out (at most {tier['agents']} part(s) at once, cap "
            f"{tier['cap']}) is the orchestrating session's: one `konstant task gate` per part")
    research_step(ctx, cat, rec, run_dir, a.harness)
    pr = PhaseRunner(rec, cat, harness, run_dir=Path(run_dir),
                     max_parallel=max_parallel(cfg.data["harness"]),
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
