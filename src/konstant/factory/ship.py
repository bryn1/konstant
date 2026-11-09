"""`konstant ship JOB` (docs/LEVEL5.md 5): ship the exact commit the verifier passed, check the
shipped state, roll it back when it fails. Code decides every step; no model is involved.

1. prepare: the job, its goal's [ship] (shiprules.conf), the evidence COMMIT=. The commit is
   copied out of the job clone into konstant's own ship repository object by object, each
   re-hashed (shiprepo.import_from_clone): what ships is the id the verifier ran the holdouts on,
   whatever the clone's .git says (replace refs, grafts, config, hooks are never read).
2. the guard, code-side (shiprules + the target's precheck: remote and local tip still at the
   clone's base, a clean worktree, gh present) and board-side (POST /api/jobs/{ref}/ships with
   dry_run first, then for real: the board repeats rules 1-7 over its own records). A refusal
   moves nothing; an owner-decision refusal (5.4, a moved target) escalates DECISION.
3. the target moves (factory/targets.py); a refused push/merge leaves it as it was (`failed`).
4. post-ship checks (factory/postship.py); a failure rolls back, then the tree is checked against
   the pre-ship tree and a follow-up job is filed by code (or BLOCKED after max_rollbacks). A
   failed rollback records `rollback_failed`, which halts ALL shipping (the board writes the
   halt) and escalates ROLLBACK_FAILED. Nothing is retried, forced or reset.
Exit: 0 shipped and the checks passed, 1 refused (nothing moved), 3 shipped and rolled back,
4 the rollback failed (shipping halted), 2 not found / setup.
"""
from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path

from konstant.factory import notify, postship, shiprepo, shiprules, targets

EXIT_SHIPPED, EXIT_REFUSED, EXIT_USAGE, EXIT_ROLLED_BACK, EXIT_HALTED = 0, 1, 2, 3, 4


def err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def lock(home):
    d = Path(home) / "var" / "locks"
    d.mkdir(parents=True, exist_ok=True)
    fh = open(d / "ship.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def _clone_dir(cfg, job: dict):
    return cfg.resolve(job["workdir"]) if job.get("workdir") else None


def prepare(cfg, client, ref) -> dict:
    """Everything the guard and the ship need, plus the code-side rules."""
    from konstant import integrity
    job = client.get(f"/api/jobs/{ref}")
    spec, goal = None, None
    if job.get("goal_id") is not None:
        goal = client.get(f"/api/goals/{job['goal_id']}")
        spec = goal["spec"]
    conf = shiprules.conf(cfg, spec)
    ev = job.get("evidence") or {}
    commit = (ev.get("commit") or "").strip()
    pre = job.get("workdir_base") or ""
    projects = client.get("/api/projects")["projects"]
    proj = next(p for p in projects if p["slug"] == job["project"])
    target = cfg.resolve(proj["path"])
    plan = {"job": job, "goal": goal, "conf": conf, "commit": commit, "pre": pre,
            "target": target, "slug": proj["slug"], "rules": [], "repo": None, "tgt": None}
    rules = plan["rules"]
    vers = job.get("verifications") or []
    last = vers[-1] if vers else None
    sealed = [r for r in job.get("holdouts") or [] if r["state"] == "sealed"]
    need = ((spec or {}).get("holdout") or {}).get("min_per_job") or \
        cfg.data["holdout"]["min_per_job"]
    rules += shiprules.verified_rules(job, last, sealed, need, commit or "-")
    if not all(r[1] for r in rules) or not shiprepo.full_sha(commit) or \
            not shiprepo.full_sha(pre):
        if not shiprepo.full_sha(pre):
            rules.append(shiprules.bad("base", "the job has no job clone base: only a factory "
                                               "job (a claimed holdout job) ships"))
        return plan
    clone = _clone_dir(cfg, job)
    try:
        repo = shiprepo.ensure(cfg, proj["slug"], target)
        n = shiprepo.import_from_clone(cfg, repo, clone, commit)
        shiprepo.out(repo, "cat-file", "-e", f"{pre}^{{commit}}")
        plan["repo"] = repo
        rules.append(shiprules.ok("import", f"{commit[:12]} is in konstant's ship repository "
                                            f"({n} new object(s) copied out of the job clone, "
                                            "each re-hashed); the clone's refs and config unread"))
    except (shiprepo.ShipRepoError, OSError) as exc:
        rules.append(shiprules.bad("import", f"refused: {exc}"))
        return plan
    why = integrity.require(cfg)
    rules.append(shiprules.bad("catalog", why) if why else
                 shiprules.ok("catalog", "catalog/ matches var/machinery.json"))
    if goal is not None and goal["status"] != "active":
        rules.append(shiprules.bad("goal", f"goal {goal['slug']} is {goal['status']}"))
    h = client.get("/api/factory/shipping")
    if h["shipping"] == "halted":
        rules.append(shiprules.bad("halt", f"shipping is halted since {h['since']} "
                                           f"({h['reason']})"))
    rules += code_decisions(cfg, client, plan, sealed)
    plan["tgt"] = targets.make(cfg, conf, target, repo, {**job, "commit": commit}, pre)
    rules += plan["tgt"].precheck()
    return plan


def code_decisions(cfg, client, plan: dict, sealed: list) -> list:
    job, conf, repo = plan["job"], plan["conf"], plan["repo"]
    reasons = []
    if job["type"] in cfg.data["ship"]["decision_types"] or job.get("ship_mode") == "decision":
        reasons.append(f"job type {job['type']} is an owner decision ([ship] decision_types)")
    if shiprules.regression_only(sealed) and not conf["regression_only"]:
        reasons.append("only regression holdouts: nothing proved the change")
    paths = [r[1] for r in shiprepo.changes(repo, plan["pre"], plan["commit"])]
    reasons += shiprules.decision_paths(paths)
    if conf["target"] in ("github", "command"):
        try:
            found = shiprules.secret_findings(repo, plan["pre"], plan["commit"],
                                              shiprules.patterns(cfg))
        except Exception as exc:  # noqa: BLE001 - an unreadable scanner fails closed
            return [shiprules.bad("decision", f"secret scan could not run: {exc}")]
        reasons += [f"secret scan finding in {f}" for f in found]
    if not reasons:
        return [shiprules.ok("decision", "no owner decision needed")]
    trail = client.get(f"/api/jobs/{job['id']}/trail")["trail"]
    if any(t["kind"] == "approval" and t["role"] == "owner" and
           (t.get("payload") or {}).get("ship_decision") == plan["commit"] for t in trail):
        return [shiprules.ok("decision", "approved by the owner for this commit: "
                                         + "; ".join(reasons))]
    return [shiprules.bad("decision", "DECISION: " + "; ".join(reasons))]


def verdict(rules: list) -> str:
    bad = [r for r in rules if not r[1]]
    if not bad:
        return "ship"
    from konstant.board.api.ships import DECISION_RULES
    return "decision" if all(r[0] in DECISION_RULES for r in bad) else "refused"


def board_check(client, plan: dict, dry: bool = True) -> dict:
    return client.post(f"/api/jobs/{plan['job']['id']}/ships",
                       {"commit": plan["commit"], "pre": plan["pre"],
                        "target": plan["conf"]["target"], "branch": plan["conf"]["branch"],
                        "dry_run": dry})


def summary(plan: dict, board: dict | None) -> dict:
    code = [{"rule": r, "ok": o, "reason": why} for r, o, why in plan["rules"]]
    rules = code + [dict(r, side="board") for r in (board or {}).get("rules", [])]
    allr = [(r["rule"], r["ok"], r["reason"]) for r in rules]
    return {"job": plan["job"]["id"], "display_id": plan["job"]["display_id"],
            "decision": verdict(allr), "commit": plan["commit"], "pre": plan["pre"],
            "target": plan["conf"]["target"], "branch": plan["conf"]["branch"], "rules": rules}


def escalate(cfg, client, plan: dict, event: str, reason: str) -> None:
    goal = (plan.get("goal") or {}).get("slug", "")
    job = plan["job"]
    notify.emit(cfg, event, goal, job["id"], job["display_id"], reason)
    try:
        client.post(f"/api/jobs/{job['id']}/trail", {"kind": "escalation",
                                                     "body": f"{event}: {reason}"[:1000]})
    except Exception:  # noqa: BLE001 - the event file already holds it
        pass


def dry_run(cfg, client, ref) -> dict:
    plan = prepare(cfg, client, ref)
    board = board_check(client, plan) if plan["repo"] is not None else None
    return summary(plan, board)


def first_reason(res: dict) -> str:
    bad = [r for r in res["rules"] if not r["ok"]]
    return bad[0]["reason"] if bad else ""


def ship(cfg, client, ref, out=print) -> tuple:
    """-> (exit code, result dict). `client` acts as the factory identity."""
    fh = lock(cfg.home)
    if fh is None:
        return EXIT_REFUSED, {"decision": "refused", "reason": "another ship runs (one ship at a "
                                                              "time)"}
    plock = None
    try:
        plan = prepare(cfg, client, ref)
        from konstant.cli.task_run import project_lock
        plock = project_lock(cfg.home, plan["target"])
        if plock is None:
            return EXIT_REFUSED, {"decision": "refused", "reason": "a task run holds the target"}
        board = board_check(client, plan) if plan["repo"] is not None else None
        res = summary(plan, board)
        if res["decision"] != "ship":
            if res["decision"] == "decision":
                escalate(cfg, client, plan, "DECISION",
                         first_reason(res).removeprefix("DECISION: "))
            return EXIT_REFUSED, res
        made = board_check(client, plan, dry=False)
        if "ship" not in made:
            res = summary(plan, made)
            return EXIT_REFUSED, res
        return execute(cfg, client, plan, made["ship"], res)
    finally:
        if plock not in (None, True):
            plock.close()
        fh.close()


def execute(cfg, client, plan: dict, sid: int, res: dict) -> tuple:
    tgt, commit, job = plan["tgt"], plan["commit"], plan["job"]
    goal = (plan.get("goal") or {}).get("slug", "")
    res["ship"] = sid
    try:
        tip = tgt.ship(sid, commit)
    except targets.TargetRefused as exc:
        client.post(f"/api/ships/{sid}", {"state": "failed", "reason": str(exc)})
        escalate(cfg, client, plan, "DECISION", str(exc))
        res.update(state="failed", reason=str(exc))
        return EXIT_REFUSED, res
    except Exception as exc:  # noqa: BLE001 - not knowing whether the target moved halts shipping
        why = f"ship {sid}: {type(exc).__name__} while moving the target: {exc}"[:400]
        client.post("/api/factory/shipping", {"action": "halt", "reason": why})
        escalate(cfg, client, plan, "HALTED", why + "; ALL shipping is halted until `konstant "
                 "--as owner factory resume-shipping`")
        res.update(state="shipping", reason=why)
        return EXIT_HALTED, res
    client.post(f"/api/ships/{sid}", {"state": "shipped", "tip": tip})
    return after_move(cfg, client, plan, sid, tip, res)


def after_move(cfg, client, plan: dict, sid: int, tip: str, res: dict) -> tuple:
    """The target is at `tip` and the ship row says `shipped`: the post-ship checks, then keep it
    or roll it back (also where a resumed factory continues an interrupted ship: reconcile.py)."""
    tgt, commit, job = plan["tgt"], plan["commit"], plan["job"]
    goal = (plan.get("goal") or {}).get("slug", "")
    res.update(ship=sid, state="shipped", tip=tip)
    post = postship.run(cfg, client, tgt, job, plan["conf"], commit, tip)
    res["post"] = post
    if post["ok"]:
        client.post(f"/api/ships/{sid}", {"state": "shipped", "post": post})
        notify.emit(cfg, "SHIPPED", goal, job["id"], job["display_id"],
                    f"ship {sid}: {commit[:12]} -> {plan['conf']['target']} "
                    f"{plan['conf']['branch']} ({tip[:12]})")
        return EXIT_SHIPPED, res
    why = "; ".join(post["failed"])[:900]
    try:
        rb = tgt.rollback(sid, tip)
    except Exception as exc:  # noqa: BLE001 - RollbackFailed or anything else: the same halt
        client.post(f"/api/ships/{sid}", {"state": "rollback_failed", "post": post,
                                          "reason": f"post-ship: {why}; rollback: {exc}"})
        escalate(cfg, client, plan, "ROLLBACK_FAILED", f"ship {sid}: rollback failed ({exc}); "
                 "ALL shipping is halted until `konstant --as owner factory resume-shipping`")
        res.update(state="rollback_failed", reason=str(exc))
        return EXIT_HALTED, res
    client.post(f"/api/ships/{sid}", {"state": "rolled_back", "rollback": rb, "post": post,
                                      "reason": f"post-ship check failed: {why}"})
    res.update(state="rolled_back", rollback=rb)
    notify.emit(cfg, "ROLLED_BACK", goal, job["id"], job["display_id"],
                f"ship {sid} rolled back: {why}")
    res["follow_up"] = follow_up(cfg, client, plan, sid, post)
    return EXIT_ROLLED_BACK, res


def follow_up(cfg, client, plan: dict, sid: int, post: dict):
    """5.3 step 4: a follow-up job by code, or BLOCKED after the goal's max_rollbacks."""
    goal, job = plan.get("goal"), plan["job"]
    if goal is not None:
        cap = goal["spec"]["limits"].get("max_rollbacks") or 0
        n = sum(1 for s in client.get("/api/ships")["ships"]
                if s.get("goal_id") == goal["id"] and s["state"] == "rolled_back")
        if cap and n > cap:
            escalate(cfg, client, plan, "BLOCKED", f"goal {goal['slug']}: {n} rollbacks, "
                     f"max_rollbacks = {cap}: no follow-up job is filed")
            return None
    probe = (post.get("failed_probes") or [""])[0]
    new = client.post(f"/api/ships/{sid}/follow-up", {"probe": probe})
    copy_holdouts(cfg, job["id"], new["id"])
    return new["id"]


def copy_holdouts(cfg, src: int, dst: int) -> None:
    """The original scenario files, sealed again for the follow-up job (same bytes, so the same
    commitments the board copied)."""
    from konstant.holdout import store
    sd, dd = store.job_dir(cfg, src), store.job_dir(cfg, dst)
    dd.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(dd, 0o700)
    for f in sorted(sd.glob("H*.scenario")):
        data = f.read_bytes()
        out = dd / f.name
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
