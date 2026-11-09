"""Ships on the board (docs/LEVEL5.md 5): the board's own copy of the ship guard, the ship record,
the follow-up after a rollback and the shipping halt.

POST /api/jobs/{ref}/ships          the factory identity only: the guard (factory/shiprules.py over
                                    the board's own records, the ship repository konstant owns and
                                    the target), then a `shipping` row; `dry_run` answers the guard
                                    without writing
POST /api/jobs/{ref}/ship-decision  the owner approves shipping one exact commit past the owner
                                    decision rules (5.4): an `approval` trail row
POST /api/ships/{id}                the factory records the outcome: shipped | failed (nothing
                                    moved) | rolled_back | rollback_failed (which HALTS shipping)
POST /api/ships/{id}/follow-up      after a rollback: a follow-up job written by code (the original
                                    acceptance + the failed post-ship probe) with the original
                                    holdout commitments sealed again for it
GET  /api/ships, /api/factory/shipping; POST /api/factory/shipping (resume: owner; halt: owner or
                                    the factory)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from konstant.board import db, tree
from konstant.board.api.deps import Actor, add_trail, load_job, reader, serialize, writer
from konstant.board.redact import redact, redact_obj
from konstant.factory import shiprules

router = APIRouter()
FACTORY = "factory"
DECISION_RULES = ("decision", "base", "worktree")
INFLIGHT = "state = 'shipping' OR (state = 'shipped' AND post_json IS NULL)"


def _is_factory(actor: Actor) -> bool:
    from konstant.board.policy import role_of
    return actor.label == FACTORY and role_of(FACTORY) == actor.role


def _need_factory(actor: Actor, what: str) -> None:
    if not _is_factory(actor):
        raise HTTPException(403, f"{what} is the factory identity's step (this token is "
                                 f"{actor.label}, role {actor.role})")


class ShipIn(BaseModel):
    commit: str
    pre: str
    target: str
    branch: str = ""
    dry_run: bool = False


class DecisionIn(BaseModel):
    commit: str
    reason: str = ""


class StateIn(BaseModel):
    state: str
    tip: str = ""
    rollback: str = ""
    post: dict | None = None
    reason: str = ""


class FollowIn(BaseModel):
    probe: str = ""


class ShippingIn(BaseModel):
    action: str
    reason: str = ""


def halted(conn) -> dict | None:
    row = conn.execute("SELECT * FROM shipping_log ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row and row["state"] == "halted" else None


def _spec(conn, job):
    if job["goal_id"] is None:
        return None, None
    g = conn.execute("SELECT * FROM goals WHERE id=?", (job["goal_id"],)).fetchone()
    return g, json.loads(g["spec_json"])


def approved(conn, job_id: int, commit: str) -> bool:
    for r in conn.execute("SELECT role, payload_json FROM trail WHERE job_id=? AND "
                          "kind='approval'", (job_id,)).fetchall():
        p = json.loads(r["payload_json"]) if r["payload_json"] else {}
        if r["role"] == "owner" and p.get("ship_decision") == commit:
            return True
    return False


def board_guard(request: Request, conn, job, body: ShipIn) -> list:
    """The board's copy of the guard (5.2): every rule that the board's records, the ship
    repository and the local target can decide."""
    from konstant import integrity
    from konstant.factory import clone, shiprepo
    cfg = request.app.state.cfg
    jd = serialize(conn, job)
    ver = conn.execute("SELECT verdict, holdout_json FROM verifications WHERE job_id=? ORDER BY "
                       "id DESC LIMIT 1", (job["id"],)).fetchone()
    from konstant.board.api.holdouts import listing
    sealed = [r for r in listing(conn, job["id"]) if r["state"] == "sealed"]
    goal, spec = _spec(conn, job)
    conf = shiprules.conf(cfg, spec)
    need = (spec or {}).get("holdout", {}).get("min_per_job") or cfg.data["holdout"]["min_per_job"]
    if not shiprepo.full_sha(body.commit) or not shiprepo.full_sha(body.pre):
        return [shiprules.bad("commit", "commit and pre must be full object ids")]
    rules = shiprules.verified_rules(jd, dict(ver) if ver else None, sealed, need, body.commit)
    base = job["workdir_base"]
    proj = conn.execute("SELECT slug, path FROM projects WHERE id=?", (job["project_id"],)).fetchone()
    if body.target != conf["target"] or (body.branch or conf["branch"]) != conf["branch"]:
        rules.append(shiprules.bad("target", f"the job ships to {conf['target']} "
                                             f"{conf['branch']}, not {body.target} {body.branch}"))
    tip = None
    if conf["target"] in ("branch", "github"):
        try:
            tip = clone.target_tip(cfg.resolve(proj["path"]))
        except clone.CloneError as exc:
            rules.append(shiprules.bad("base", str(exc)))
    if not base or body.pre != base or (tip is not None and tip != base):
        rules.append(shiprules.bad("base", f"target moved: expected {base}, the target is at "
                                           f"{tip or body.pre}"))
    else:
        rules.append(shiprules.ok("base", f"the target is still at the clone's base {base[:12]}"))
    rules += decision_rules(cfg, conn, job, conf, sealed, body, proj["slug"])
    if goal is not None and goal["status"] != "active":
        rules.append(shiprules.bad("goal", f"goal {goal['slug']} is {goal['status']}"))
    h = halted(conn)
    if h:
        rules.append(shiprules.bad("halt", f"shipping is halted since {h['at']} ({h['reason']}): "
                                           "`konstant --as owner factory resume-shipping`"))
    busy = conn.execute(f"SELECT id FROM ships WHERE {INFLIGHT}").fetchone()
    if busy:
        rules.append(shiprules.bad("lock", f"ship {busy['id']} is in flight: one ship at a time"))
    done = conn.execute("SELECT id, state FROM ships WHERE job_id=? AND state <> 'failed'",
                        (job["id"],)).fetchone()
    if done:
        rules.append(shiprules.bad("once", f"job {job['id']} was shipped already (ship "
                                           f"{done['id']}, {done['state']})"))
    why = integrity.require(cfg)
    rules.append(shiprules.bad("catalog", why) if why else
                 shiprules.ok("catalog", "catalog/ matches var/machinery.json"))
    return rules


def decision_rules(cfg, conn, job, conf, sealed, body, slug) -> list:
    """5.4: the type, the diff's paths, a regression-only set and (github/command) the secret scan;
    each may be passed by the owner's approval of this exact commit."""
    from konstant.factory import shiprepo
    reasons = []
    if job["type"] in cfg.data["ship"]["decision_types"] or job["ship_mode"] == "decision":
        reasons.append(f"job type {job['type']} is an owner decision ([ship] decision_types)")
    if shiprules.regression_only(sealed) and not conf["regression_only"]:
        reasons.append("only regression holdouts: nothing proved the change")
    repo = shiprepo.path_for(cfg, slug)
    try:
        shiprepo.out(repo, "cat-file", "-e", f"{body.commit}^{{commit}}")
        paths = [p for _s, p, *_r in shiprepo.changes(repo, body.pre, body.commit)]
    except (shiprepo.ShipRepoError, OSError):
        return [shiprules.bad("import", f"the ship repository does not hold {body.commit[:12]} "
                                        "and its base: konstant imports it before it ships")]
    reasons += shiprules.decision_paths(paths)
    if conf["target"] in ("github", "command"):
        try:
            found = shiprules.secret_findings(repo, body.pre, body.commit, shiprules.patterns(cfg))
        except Exception as exc:  # noqa: BLE001 - an unreadable scanner fails closed
            return [shiprules.bad("decision", f"secret scan could not run: {exc}")]
        reasons += [f"secret scan finding in {f}" for f in found]
    if not reasons:
        return [shiprules.ok("decision", "no owner decision needed")]
    if approved(conn, job["id"], body.commit):
        return [shiprules.ok("decision", "approved by the owner for this commit: "
                                         + "; ".join(reasons))]
    return [shiprules.bad("decision", "DECISION: " + "; ".join(reasons))]


@router.post("/api/jobs/{ref}/ships")
def create(ref: str, body: ShipIn, request: Request, actor: Actor = Depends(writer)):
    _need_factory(actor, "shipping")
    with db.transaction(request.app.state.db_path) as conn:
        job = load_job(conn, ref)
        rules = board_guard(request, conn, job, body)
        bad = [r for r in rules if not r[1]]
        decision = ("ship" if not bad else "decision" if all(r[0] in DECISION_RULES for r in bad)
                    else "refused")
        out = {"job": job["id"], "decision": decision, "commit": body.commit, "pre": body.pre,
               "rules": [{"rule": r, "ok": o, "reason": why} for r, o, why in rules]}
        if body.dry_run or bad:
            return out
        sid = conn.execute(
            "INSERT INTO ships (job_id, goal_id, target, branch, commit_sha, pre_ref, state, "
            "actor) VALUES (?,?,?,?,?,?,'shipping',?)",
            (job["id"], job["goal_id"], body.target, body.branch or None, body.commit, body.pre,
             actor.label)).lastrowid
        add_trail(conn, job["id"], actor, "ship", f"ship {sid}: shipping {body.commit[:12]} to "
                  f"{body.target} {body.branch} (from {body.pre[:12]})",
                  {"ship": sid, "commit": body.commit, "pre": body.pre, "state": "shipping"})
        out["ship"] = sid
        return out


@router.post("/api/jobs/{ref}/ship-decision")
def decide(ref: str, body: DecisionIn, request: Request, actor: Actor = Depends(writer)):
    if actor.role != "owner":
        raise HTTPException(403, "an owner decision at ship time needs the owner role")
    from konstant.factory import shiprepo
    if not shiprepo.full_sha(body.commit):
        raise HTTPException(422, "name the exact commit (a full object id)")
    with db.transaction(request.app.state.db_path) as conn:
        job = load_job(conn, ref)
        ev = json.loads(job["evidence_json"]) if job["evidence_json"] else {}
        if job["status"] != "verified" or ev.get("commit") != body.commit:
            raise HTTPException(409, f"job {job['id']} is {job['status']} with evidence commit "
                                     f"{ev.get('commit')}: the owner approves shipping the "
                                     "verified commit only")
        tid = add_trail(conn, job["id"], actor, "approval", "owner decision: ship "
                        f"{body.commit[:12]}" + (f" ({redact(body.reason)})" if body.reason else ""),
                        {"ship_decision": body.commit})
    return {"job": job["id"], "trail_id": tid, "commit": body.commit}


def ship_row(conn, sid) -> dict:
    row = conn.execute("SELECT * FROM ships WHERE id=?", (sid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"ship {sid} not found")
    out = dict(row)
    out["post"] = json.loads(out.pop("post_json")) if row["post_json"] else None
    out["display_id"] = tree.display_id(conn, row["job_id"])
    return out


@router.post("/api/ships/{sid}")
def record(sid: int, body: StateIn, request: Request, actor: Actor = Depends(writer)):
    _need_factory(actor, "recording a ship")
    from konstant.factory import shiprepo
    for v in (body.tip, body.rollback):
        if v and not shiprepo.full_sha(v):
            raise HTTPException(422, "tip and rollback are full object ids")
    with db.transaction(request.app.state.db_path) as conn:
        s = ship_row(conn, sid)
        fields = {"state": body.state, "updated_at": None}
        if body.state == "shipped" and s["state"] == "shipping" and not body.tip:
            raise HTTPException(422, "a shipped state names the target's new tip")
        if body.state == "rolled_back" and not body.rollback:
            raise HTTPException(422, "a rolled_back state names the rollback commit")
        if body.tip:
            fields["tip_sha"] = body.tip
        if body.rollback:
            fields["rollback_sha"] = body.rollback
        if body.post is not None:
            fields["post_json"] = json.dumps(redact_obj(body.post), sort_keys=True)
        if body.reason:
            fields["reason"] = redact(body.reason)[:2000]
        cols = ", ".join(f"{k}=?" if k != "updated_at" else
                         "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')" for k in fields)
        vals = [v for k, v in fields.items() if k != "updated_at"]
        try:
            conn.execute(f"UPDATE ships SET {cols} WHERE id=?", (*vals, sid))
        except Exception as exc:  # noqa: BLE001 - a trigger refusal
            raise HTTPException(409, f"ship {sid}: {exc}") from None
        kind = "rollback" if body.state in ("rolled_back", "rollback_failed") else "ship"
        add_trail(conn, s["job_id"], actor, kind, f"ship {sid}: {body.state}"
                  + (f": {redact(body.reason)[:300]}" if body.reason else ""),
                  {"ship": sid, "state": body.state, "tip": body.tip or None,
                   "rollback": body.rollback or None})
        if body.state == "rollback_failed":
            conn.execute("INSERT INTO shipping_log (state, reason, ship_id, actor) VALUES "
                         "('halted', ?, ?, ?)", (f"ship {sid}: rollback failed", sid, actor.label))
        return ship_row(conn, sid)


def follow_up_brief(job, s: dict, probe: str) -> str:
    failed = ", ".join((s.get("post") or {}).get("failed") or []) or "a post-ship check"
    text = (job["brief"].rstrip() + f"\n- after ship {s['id']} the post-ship check(s) that "
            f"failed on the target pass: {failed}\n")
    return text + (probe.strip() + "\n" if probe else "")


@router.post("/api/ships/{sid}/follow-up")
def follow_up(sid: int, body: FollowIn, request: Request, actor: Actor = Depends(writer)):
    """5.3 step 4: the follow-up job is written by code: the original brief and acceptance plus the
    failed post-ship probe as a new PROBE row; the original holdout commitments sealed again."""
    _need_factory(actor, "a follow-up job")
    from konstant.board import dod
    with db.transaction(request.app.state.db_path) as conn:
        s = ship_row(conn, sid)
        if s["state"] != "rolled_back" or s["follow_up_id"] is not None:
            raise HTTPException(409, f"ship {sid} is {s['state']}"
                                + (f" with follow-up job {s['follow_up_id']}"
                                   if s["follow_up_id"] else "")
                                + ": a follow-up is filed once, after a rollback")
        probe = body.probe.strip()
        if probe and probe not in ((s.get("post") or {}).get("failed_probes") or []):
            raise HTTPException(422, "the follow-up's PROBE must be a post-ship probe that failed")
        job = load_job(conn, str(s["job_id"]))
        brief = follow_up_brief(job, s, probe)
        title = f"follow-up of {s['display_id']} after rollback of ship {sid}: {job['title']}"[:500]
        jid = conn.execute(
            "INSERT INTO jobs (project_id, parent_id, type, title, brief, acceptance, status, "
            "priority, requested_by, approval_required, holdout_required, goal_id, budget_json, "
            "ship_mode) VALUES (?,?,?,?,?,?,'queued',?,?,0,1,?,?,?)",
            (job["project_id"], job["parent_id"], job["type"], redact(title), brief,
             dod.extract_acceptance(brief), job["priority"], actor.label, job["goal_id"],
             job["budget_json"], job["ship_mode"])).lastrowid
        add_trail(conn, jid, actor, "status", f"filed as queued: follow-up of job {job['id']} "
                  f"after ship {sid} was rolled back")
        rows = conn.execute("SELECT hid, kind, sha256 FROM holdouts WHERE job_id=? AND "
                            "state='sealed' ORDER BY id", (job["id"],)).fetchall()
        tid = add_trail(conn, jid, actor, "holdout", f"sealed {', '.join(r['hid'] for r in rows)} "
                        f"again from job {job['id']} (same commitments)",
                        {"event": "sealed", "hids": [r["hid"] for r in rows], "generation": 1,
                         "copied_from": job["id"]})
        for r in rows:
            conn.execute("INSERT INTO holdouts (job_id, hid, kind, sha256, author_label, "
                         "generation, trail_id) VALUES (?,?,?,?,?,1,?)",
                         (jid, r["hid"], r["kind"], r["sha256"], actor.label, tid))
        conn.execute("UPDATE ships SET follow_up_id=? WHERE id=?", (jid, sid))
        add_trail(conn, job["id"], actor, "rollback", f"ship {sid}: follow-up job {jid} filed",
                  {"ship": sid, "follow_up": jid})
        out = serialize(conn, conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
    out["holdouts_from"] = job["id"]
    return out


@router.get("/api/ships")
def list_ships(request: Request, job: str = "", actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        q, args = "SELECT id FROM ships", []
        if job:
            q += " WHERE job_id=?"
            args.append(load_job(conn, job)["id"])
        return {"ships": [ship_row(conn, r["id"]) for r in conn.execute(q + " ORDER BY id", args)]}


@router.get("/api/factory/shipping")
def shipping(request: Request, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        h = halted(conn)
        return {"shipping": "halted" if h else "open", "since": h["at"] if h else None,
                "reason": h["reason"] if h else None, "ship": h["ship_id"] if h else None}


@router.post("/api/factory/shipping")
def set_shipping(body: ShippingIn, request: Request, actor: Actor = Depends(writer)):
    if body.action == "resume" and actor.role != "owner":
        raise HTTPException(403, "only the owner resumes shipping after a failed rollback")
    if body.action == "halt" and actor.role != "owner" and not _is_factory(actor):
        raise HTTPException(403, "shipping is halted by the owner or the factory identity")
    if body.action not in ("halt", "resume"):
        raise HTTPException(422, "action is halt or resume")
    with db.transaction(request.app.state.db_path) as conn:
        if (halted(conn) is not None) == (body.action == "halt"):
            raise HTTPException(409, f"shipping is already {'halted' if body.action == 'halt' else 'open'}")
        conn.execute("INSERT INTO shipping_log (state, reason, actor) VALUES (?,?,?)",
                     ("halted" if body.action == "halt" else "resumed",
                      redact(body.reason or body.action), actor.label))
    return {"shipping": "halted" if body.action == "halt" else "open"}
