"""`konstant intake GOAL` (docs/LEVEL5.md 4.2): goal -> jobs with a reviewed DoD -> sealed
holdouts, in that order, each step by a different identity.

1. Planner phase + DoD review phase: a task run of the flag-only type `intake` (catalog), every
   phase in konstant's jail (factory mode; no jail = exit 2 `holdouts need a confined phase`),
   working in OUT under the run dir with the target read-only. The planner acts as `planner`, the
   reviewer as `dod-reviewer` (types.yaml `identity`); authorship and the `# JUDGED:` pin over the
   backlog and the briefs are the existing rules; the `backlog` rule (factory/backlog.py) holds
   the run UNMET while a brief would be refused, so the planner is resumed with the reasons.
2. Deterministic filing, after `task check` is MET: backlog.lint() again (same inputs); any reason
   files nothing (exit 3, one `UNMET: ...` line each). Then, while the factory identity holds the
   goal's intake at `filing` (board), every job is filed under the goal's project as `planner`
   (waiting_approval, holdout_required, goal_id, budget, ship mode computed by the board), its
   `dod-review SHIP` posted as `dod-reviewer` (the line the verdict file states), the intake set
   `filed` (once per goal), and each job approved as `factory`.
3. Holdouts: `[holdout] author = "agent"` -> the scenario writer (holdout/author.py) seals each
   job's set as `scenario`; `owner` -> the jobs wait for `holdout add` (the claim guard holds them).
Escalations (`BLOCKED`) and the outcome (`FILED`) go through factory/notify.py.
Exit: 0 filed (and sealed when author = agent), 3 refused (nothing filed), 4 filed but a job's
holdout authoring BLOCKED, 2 setup (no jail, goal not active, intake already filed), 5 error.
"""
from __future__ import annotations

import sys
from pathlib import Path

from konstant.client import ClientError

EXIT_OK, EXIT_USAGE, EXIT_UNMET, EXIT_BLOCKED, EXIT_ERROR = 0, 2, 3, 4, 5


def err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def task_text(g: dict, target: Path, cat) -> str:
    spec = g["spec"]
    cap = spec["limits"]["max_jobs"]
    return (f"[konstant intake] goal {g['slug']} for project {g['project']}: plan the jobs that "
            "reach this goal.\n\nGOAL:\n" + spec["goal"]["text"].strip() + "\n\n"
            f"TARGET (read-only, as it is now): {target}\n"
            f"LIMITS: max_jobs {cap or 'not limited'}; every job gets max_attempts "
            f"{spec['limits']['max_attempts']}.\n"
            f"Job types you may use: {', '.join(cat.classifiable())}.\n"
            "Write OUT/BACKLOG.md and one brief per row in OUT/jobs/B<n>.md as your profile "
            "says; result paths in PROBE lines as {workdir}/<path>.\n")


def _refuse(ctx, slug: str, lines: list, code: int, event: bool = True) -> int:
    from konstant.factory import notify
    for ln in lines:
        print(ln)
    try:
        ctx.client("factory").post(f"/api/goals/{slug}/intake", {"state": "refused"})
    except ClientError:
        pass
    if event:
        notify.emit(ctx.cfg, "BLOCKED", slug, reason="intake refused, nothing filed: "
                    + (lines[0] if lines else "no reason"))
    return code


def run(ctx, slug: str, override: str | None = None) -> int:
    from konstant import catalog as catalog_mod
    from konstant.cli.task_run import cli_template
    from konstant.factory import backlog
    from konstant.gate import harness as harness_mod
    from konstant.gate import loop, record as record_mod
    from konstant.gate.rules.backlog import roots_for
    from konstant.gate.runner import PhaseRunner
    from konstant.verify.holdout import confined
    from konstant import harnesses
    cfg = ctx.cfg
    viewer, factory = ctx.client("viewer"), ctx.client("factory")
    g = viewer.get(f"/api/goals/{slug}")
    slug = g["slug"]
    if g["status"] != "active":
        err(f"konstant intake: goal {slug} is {g['status']}: intake runs for an active goal")
        return EXIT_USAGE
    if g["intake"] in ("filing", "filed"):
        err(f"konstant intake: goal {slug} was taken in already (intake {g['intake']}, "
            f"{len(g.get('jobs') or [])} job(s)): intake runs once per goal")
        return EXIT_USAGE
    why = confined(cfg)
    cat = catalog_mod.load(catalog_mod.find_root(cfg.home, cfg.data["catalog"]["path"]),
                           check_files=True)
    over = (override if override in harnesses.ADAPTERS else cli_template(override)) \
        if override else None
    hs = harness_mod.HarnessSet(cfg.data["harness"], cfg.home, cat,
                                cfg.data["permissions"]["allow"], override=over,
                                jail=bool(cfg.data["gate"]["jail"]), factory=True)
    loose = hs.unconfined()
    if why or loose:
        err(f"konstant intake: {why or 'holdouts need a confined phase'}"
            + (f": the harness(es) {', '.join(loose)} would not run in konstant's jail"
               if loose and not why else ""))
        return EXIT_USAGE
    hs.check()
    projects = viewer.get("/api/projects")["projects"]
    target = next((cfg.resolve(p["path"]) for p in projects if p["slug"] == g["project"]), None)
    factory.post(f"/api/goals/{slug}/intake", {"state": "planning"})
    task = task_text(g, target, cat)
    run_dir, stamp, sl = record_mod.new_run_dir(cfg.home, f"intake {slug}")
    out = run_dir / "out"
    rec = record_mod.build(cat, task, "intake", "flag", run_dir=run_dir, out=out, project=None,
                           workspace=cfg.home, job=None, mode="runner", gate_cfg=cfg.data["gate"])
    rec.update(cwd=str(out.resolve()), intake=True, goal=slug, target=str(target),
               max_jobs=g["spec"]["limits"]["max_jobs"] or "not limited")
    record_mod.write(run_dir, rec)
    err(f"konstant intake: goal {slug}: [type:intake] run {run_dir} (factory mode: every phase "
        "jailed; planner and dod-reviewer identities)")
    pr = PhaseRunner(rec, cat, hs, run_dir=run_dir, max_parallel=cfg.data["harness"]["max_parallel"],
                     log=err, isolate=True)
    pr.run_all(cfg.data["gate"]["max_cycles"])
    pr.closeout()
    code, lines = loop.dod_loop(pr, None, cfg.data["gate"]["max_resumes"], err)
    if code != 0:
        name = {3: "UNMET", 4: "BLOCKED"}.get(code, "CHECK-ERROR")
        return _refuse(ctx, slug, [ln if ln.startswith(("BLOCKED:", "CHECK-ERROR"))
                                   else f"UNMET: {ln}" for ln in lines] or [name], code)
    reasons, jobs = backlog.lint(out, cat, roots_for(cfg, target),
                                 g["spec"]["limits"]["max_jobs"])
    if reasons:
        return _refuse(ctx, slug, [f"UNMET: {r}" for r in reasons], EXIT_UNMET)
    return file_jobs(ctx, g, jobs, out, target, cat, override)


def file_jobs(ctx, g: dict, jobs: list, out: Path, target: Path, cat, override) -> int:
    from konstant.factory import backlog, notify
    cfg, slug = ctx.cfg, g["slug"]
    factory, planner = ctx.client("factory"), ctx.client("planner")
    reviewer = ctx.client("dod-reviewer")
    votes = backlog.verdicts(out)
    factory.post(f"/api/goals/{slug}/intake", {"state": "filing"})
    filed: dict = {}
    try:
        for bid, jtype, title, after, brief in jobs:
            res = planner.post("/api/jobs", {
                "title": f"{bid}: {title}", "project": g["project"], "brief": brief,
                "type": jtype, "goal": slug, "after": str(filed[after]) if after else ""})
            filed[bid] = res["id"]
            err(f"konstant intake: filed {bid} as job {res['display_id']} ({res['status']})")
        for bid, jid in filed.items():
            reviewer.post(f"/api/jobs/{jid}/dod-review",
                          {"verdict": "SHIP", "reason": votes[bid][1][:500]})
        factory.post(f"/api/goals/{slug}/intake", {"state": "filed"})
        for jid in filed.values():
            factory.post(f"/api/jobs/{jid}/approve")
    except ClientError as exc:
        notify.emit(cfg, "BLOCKED", slug, reason=f"intake filing failed after {len(filed)} "
                    f"job(s): {exc.message}")
        raise
    rows = [viewer_job(ctx, jid) for jid in filed.values()]
    blocked = seal_all(ctx, g, rows, target, cat, override)
    ids = ", ".join(r["display_id"] for r in rows)
    notify.emit(cfg, "FILED", slug, reason=f"{len(rows)} job(s) filed with a reviewed DoD "
                f"({ids}); holdouts {'sealed' if not blocked else 'BLOCKED for ' + str(len(blocked))}"
                + (" (author = owner: `holdout add` each)" if g["spec"]["holdout"]["author"]
                   == "owner" else ""))
    ctx.out({"goal": slug, "jobs": rows, "blocked": blocked},
            "\n".join(f"job {r['display_id']} {r['status']} {r['title']} (holdouts "
                      f"{sum(h['state'] == 'sealed' for h in r['holdouts'])} sealed)"
                      for r in rows))
    return EXIT_BLOCKED if blocked else EXIT_OK


def viewer_job(ctx, jid) -> dict:
    return ctx.client("viewer").get(f"/api/jobs/{jid}")


def seal_all(ctx, g: dict, rows: list, target: Path, cat, override) -> list:
    """The scenario writer for each job (author = agent); returns the blocked job ids."""
    from konstant.factory import notify
    from konstant.holdout import author
    cfg, blocked = ctx.cfg, []
    if g["spec"]["holdout"]["author"] != "agent":
        err("konstant intake: holdout.author = owner: every job waits for `konstant holdout add`")
        return []
    need = max(g["spec"]["holdout"]["min_per_job"], cfg.data["holdout"]["min_per_job"])
    for i, job in enumerate(rows):
        try:
            res = author.author(cfg, cat, job, g["spec"]["goal"]["text"], target,
                                ctx.client("scenario"), need, override, log=err)
        except author.AuthorRefused as exc:
            res = {"blocked": f"{author.BLOCKED}: job {job['display_id']}: {exc}"}
        if "blocked" in res:
            blocked.append(job["id"])
            notify.emit(cfg, "BLOCKED", g["slug"], job["id"], job["display_id"], res["blocked"])
            ctx.client("factory").post(f"/api/jobs/{job['id']}/trail",
                                       {"kind": "escalation", "body": res["blocked"]})
        rows[i] = viewer_job(ctx, job["id"])
    return blocked
