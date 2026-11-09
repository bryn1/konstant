"""An interrupted ship, reconciled on resume (docs/LEVEL5.md 6.1: every step is an idempotent board
transition; the known gap of L5-4 closed).

A ship killed with its process (or the host) leaves its board row in flight: `shipping` (the guard
then refuses every other ship: one at a time) or `shipped` without post-ship checks. The factory
loop, before any new ship and only while no ship holds the ship lock, compares the TARGET with the
row and never leaves it blocking:

  shipping, target still at the row's pre        -> `failed` (nothing moved); the job ships again
  shipping, target at the shipped commit         -> `shipped` (branch: the worktree rewrite is
            (github: a merge whose tree is it)      finished, github: the local target moved), then
                                                    the post-ship checks run as after a ship
  shipped without checks, target at its tip      -> the post-ship checks run (keep or roll back)
  shipped without checks, target at a commit     -> `rolled_back` (the rollback finished, its
            on the tip whose tree is pre's          record did not), follow-up job filed
  anything else, or an apply / command target     -> recorded as it ends (`failed` for a shipping
            whose move konstant cannot read            row, `rollback_failed` for a shipped one),
                                                    ALL shipping halted, escalated: konstant does
                                                    not guess what a target it cannot read did
"""
from __future__ import annotations

from konstant.factory import shiprepo, shiprules, targets
from konstant.factory.localtarget import _checked_out, local_tip, move_local, sync_worktree


def inflight(client) -> list:
    return [s for s in client.get("/api/ships")["ships"]
            if s["state"] == "shipping" or (s["state"] == "shipped" and s.get("post") is None)]


def plan_for(cfg, client, s: dict) -> dict:
    job = client.get(f"/api/jobs/{s['job_id']}")
    goal = client.get(f"/api/goals/{job['goal_id']}") if job.get("goal_id") else None
    conf = shiprules.conf(cfg, goal["spec"] if goal else None)
    proj = next(p for p in client.get("/api/projects")["projects"] if p["slug"] == job["project"])
    target = cfg.resolve(proj["path"])
    repo = shiprepo.ensure(cfg, proj["slug"], target)
    commit, pre = s["commit_sha"], s["pre_ref"]
    tgt = targets.make(cfg, conf, target, repo, {**job, "commit": commit}, pre)
    return {"job": job, "goal": goal, "conf": conf, "commit": commit, "pre": pre,
            "target": target, "slug": proj["slug"], "rules": [], "repo": repo, "tgt": tgt}


def now_of(plan: dict) -> str:
    """The target's tip as konstant can read it ('' when it cannot: apply, command)."""
    tgt = plan["tgt"]
    if isinstance(tgt, targets.GithubTarget):
        return tgt.fetch()
    if isinstance(tgt, targets.BranchTarget):
        return local_tip(plan["target"], tgt.ref)
    return ""


def shipped_at(plan: dict, now: str) -> bool:
    repo, commit = plan["repo"], plan["commit"]
    if now == commit:
        return True
    try:
        return shiprepo.is_ancestor(repo, commit, now) and \
            shiprepo.tree_of(repo, now) == shiprepo.tree_of(repo, commit)
    except shiprepo.ShipRepoError:
        return False


def finish_local(plan: dict, now: str) -> None:
    """The local half of a move that was cut off: the local target to `now` (github), the
    checked-out worktree rewritten (idempotent: every changed path written again)."""
    tgt, target, repo = plan["tgt"], plan["target"], plan["repo"]
    have = local_tip(target, tgt.ref)
    if have == plan["pre"] and now != have:
        move_local(repo, target, tgt.ref, plan["pre"], now)
    elif have == now and _checked_out(target, tgt.ref):
        sync_worktree(repo, target, plan["pre"], now)


def give_up(cfg, client, plan: dict, s: dict, why: str) -> dict:
    from konstant.factory import ship
    state = "failed" if s["state"] == "shipping" else "rollback_failed"
    client.post(f"/api/ships/{s['id']}", {"state": state, "reason": why})
    try:
        client.post("/api/factory/shipping", {"action": "halt", "reason": why[:300]})
    except Exception:  # noqa: BLE001 - rollback_failed already halted it (same transaction)
        pass
    ship.escalate(cfg, client, plan, "HALTED", why + "; ALL shipping is halted until `konstant "
                  "--as owner factory resume-shipping`")
    return {"ship": s["id"], "result": state, "reason": why}


def one(cfg, client, s: dict) -> dict:
    from konstant.factory import ship
    plan = plan_for(cfg, client, s)
    sid, res = s["id"], {}
    try:
        now = now_of(plan)
    except shiprepo.ShipRepoError as exc:
        return give_up(cfg, client, plan, s, f"interrupted ship {sid}: the target cannot be read "
                                             f"({exc})")
    if s["state"] == "shipping":
        if not now:
            return give_up(cfg, client, plan, s, f"interrupted ship {sid} on a {plan['conf']['target']}"
                                                 " target: konstant cannot read whether it moved")
        if now == plan["pre"]:
            client.post(f"/api/ships/{sid}", {"state": "failed", "reason": "interrupted before the "
                                              "target moved: reconciled on resume (the target is "
                                              "still at its base); the job ships again"})
            return {"ship": sid, "result": "failed", "reason": "target never moved"}
        if not shipped_at(plan, now):
            return give_up(cfg, client, plan, s, f"interrupted ship {sid}: the target is at "
                                                 f"{now[:12]}, neither its base nor the shipped "
                                                 "commit")
        finish_local(plan, now)
        client.post(f"/api/ships/{sid}", {"state": "shipped", "tip": now})
        rc, res = ship.after_move(cfg, client, plan, sid, now, res)
        return {"ship": sid, "result": res.get("state"), "rc": rc, "reason": "the target had moved"}
    tip = s.get("tip_sha") or ""
    if now and now != tip:
        repo = plan["repo"]
        try:
            back = shiprepo.is_ancestor(repo, tip, now) and \
                shiprepo.tree_of(repo, now) == shiprepo.tree_of(repo, plan["pre"])
        except shiprepo.ShipRepoError:
            back = False
        if not back:
            return give_up(cfg, client, plan, s, f"interrupted ship {sid}: the target is at "
                                                 f"{now[:12]}, not at the shipped tip {tip[:12]}")
        finish_local(plan, now)
        client.post(f"/api/ships/{sid}", {"state": "rolled_back", "rollback": now,
                                          "post": {"ok": False, "checks": [], "failed":
                                                   ["interrupted: the rollback had finished"]},
                                          "reason": "interrupted after its rollback: reconciled"})
        follow = ship.follow_up(cfg, client, plan, sid, {"failed_probes": []})
        return {"ship": sid, "result": "rolled_back", "follow_up": follow}
    if now:
        finish_local(plan, now)
    rc, res = ship.after_move(cfg, client, plan, sid, tip, res)
    return {"ship": sid, "result": res.get("state"), "rc": rc, "reason": "post-ship checks rerun"}


def reconcile(cfg, client, log=print) -> list:
    """Every in-flight ship row, reconciled; [] when a ship is running right now (its lock)."""
    from konstant.factory import ship
    fh = ship.lock(cfg.home)
    if fh is None:
        return []
    try:
        out = []
        for s in inflight(client):
            try:
                r = one(cfg, client, s)
            except Exception as exc:  # noqa: BLE001 - unknown state: halt, never guess
                plan = {"job": {"id": s["job_id"], "display_id": s.get("display_id")},
                        "goal": None}
                r = give_up(cfg, client, plan, s, f"interrupted ship {s['id']}: reconciling "
                                                  f"failed ({type(exc).__name__}: {exc})"[:400])
            log(f"konstant factory: reconciled ship {s['id']}: {r['result']} ({r.get('reason')})")
            out.append(r)
        return out
    finally:
        fh.close()
