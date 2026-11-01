"""Holdout commitments on the board (docs/LEVEL5.md 3.2): seal and list, never content.

POST /api/jobs/{ref}/holdouts (HOLDOUT_ROLES) records sha256(file bytes) per scenario - the file's
canary is the salt - with the sealing identity and time, one `holdout` trail row, and marks the
job holdout_required. Only while the job is not claimed: queued or waiting_approval (a rotated
set is sealed while the job is back in queued). GET lists ids, kinds, commitments and states.
No route accepts or serves a command, an expectation, a hint or a canary.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from konstant.board import db
from konstant.board.api.deps import Actor, add_trail, load_job, reader, writer

router = APIRouter()
# who may seal: the owner, and the `scenario` identity (a worker-role token labelled scenario;
# docs/LEVEL5.md 2.2, 3.4) - never another worker label
HOLDOUT_ROLES = ("owner",)
HOLDOUT_LABELS = ("scenario",)


def may_seal(actor: Actor) -> bool:
    from konstant.board.policy import role_of
    return actor.role in HOLDOUT_ROLES or (actor.label in HOLDOUT_LABELS
                                           and role_of(actor.label) == actor.role)
SEAL_STATES = ("queued", "waiting_approval")
_HID = re.compile(r"^H[1-9][0-9]{0,5}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
PUBLIC = ("hid", "kind", "sha256", "state", "sealed_at", "author_label", "generation",
          "trail_id")


class OneIn(BaseModel):
    hid: str
    kind: str
    sha256: str


class SealIn(BaseModel):
    holdouts: list[OneIn]


def listing(conn, job_id: int) -> list:
    rows = conn.execute(f"SELECT {', '.join(PUBLIC)} FROM holdouts WHERE job_id=? ORDER BY "
                        "generation, CAST(substr(hid, 2) AS INTEGER)", (job_id,)).fetchall()
    return [dict(r) for r in rows]


def sealed_count(conn, job_id: int) -> int:
    return conn.execute("SELECT count(*) FROM holdouts WHERE job_id=? AND state='sealed'",
                        (job_id,)).fetchone()[0]


@router.post("/api/jobs/{ref}/holdouts")
def seal(ref: str, body: SealIn, request: Request, actor: Actor = Depends(writer)):
    if not may_seal(actor):
        raise HTTPException(403, f"sealing holdouts requires role {', '.join(HOLDOUT_ROLES)} or "
                                 f"the {', '.join(HOLDOUT_LABELS)} identity (this token is "
                                 f"{actor.label}, role {actor.role})")
    if not body.holdouts:
        raise HTTPException(422, "no holdout to seal")
    for h in body.holdouts:
        if not _HID.match(h.hid) or h.kind not in ("proof", "regression") or \
                not _SHA.match(h.sha256):
            raise HTTPException(422, "a holdout is {hid: H<n>, kind: proof|regression, "
                                     "sha256: 64 hex}")
    with db.transaction(request.app.state.db_path) as conn:
        job = load_job(conn, ref)
        if job["parent_id"] is None:
            raise HTTPException(409, f"job {job['id']} is a project root")
        if job["status"] not in SEAL_STATES:
            raise HTTPException(409, f"job {job['id']} is {job['status']}: holdouts are sealed "
                                     "only while the job is not claimed (queued or "
                                     "waiting_approval)")
        have = {r["hid"] for r in listing(conn, job["id"])}
        hids = [h.hid for h in body.holdouts]
        dup = sorted(set(hids) & have) or sorted({x for x in hids if hids.count(x) > 1})
        if dup:
            raise HTTPException(409, f"holdout id(s) {', '.join(dup)} already used on job "
                                     f"{job['id']}")
        cur = conn.execute("SELECT max(generation) FROM holdouts WHERE job_id=? AND "
                           "state='sealed'", (job["id"],)).fetchone()[0]
        if cur is None:
            last = conn.execute("SELECT max(generation) FROM holdouts WHERE job_id=?",
                                (job["id"],)).fetchone()[0]
            cur = (last or 0) + 1
        for h in body.holdouts:
            conn.execute("INSERT INTO holdouts (job_id, hid, kind, sha256, author_label, "
                         "generation) VALUES (?,?,?,?,?,?)",
                         (job["id"], h.hid, h.kind, h.sha256, actor.label, cur))
        tid = add_trail(conn, job["id"], actor, "holdout",
                        f"sealed {', '.join(hids)} ({len(hids)} scenario(s), set {cur})",
                        {"event": "sealed", "hids": hids, "generation": cur})
        conn.execute("UPDATE holdouts SET trail_id=? WHERE job_id=? AND trail_id IS NULL",
                     (tid, job["id"]))
        conn.execute("UPDATE jobs SET holdout_required=1 WHERE id=?", (job["id"],))
        rows = [r for r in listing(conn, job["id"]) if r["hid"] in hids]
    return {"job": job["id"], "holdouts": rows}


@router.get("/api/jobs/{ref}/holdouts")
def get_holdouts(ref: str, request: Request, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        job = load_job(conn, ref)
        rows = listing(conn, job["id"])
        return {"job": job["id"], "holdout_required": bool(job["holdout_required"]),
                "count": len(rows), "sealed": sum(r["state"] == "sealed" for r in rows),
                "min_per_job": request.app.state.cfg.data["holdout"]["min_per_job"],
                "holdouts": rows}


def after_verdict(conn, job, actor: Actor, word: str, holdout: dict | None, cfg) -> str | None:
    """The verdict's holdout consequences (3.5, 3.6 step 6). Returns a forced job state or None.
    A LEAK burns the sealed set. A FAIL round caused by holdouts counts against the set's
    exposure budget: after [holdout] max_failed_rounds the set is worn and retired (a fresh set
    must be sealed before the next claim: the claim guard), and a SECOND worn set blocks the job
    for the owner."""
    if not holdout:
        return None
    jid = job["id"]
    if holdout.get("leak"):
        n = conn.execute("UPDATE holdouts SET state='burned' WHERE job_id=? AND state='sealed'",
                         (jid,)).rowcount
        add_trail(conn, jid, actor, "holdout", f"holdout set burned: a canary leaked ({n} "
                  "scenario(s)); the owner reopens the job with a fresh set, or cancels it",
                  {"event": "burned", "generation": holdout.get("generation")})
        return None
    gen = holdout.get("generation")
    if word != "FAIL" or not holdout.get("failed_round") or gen is None:
        return None
    rounds = conn.execute(
        "SELECT count(*) FROM verifications WHERE job_id=? AND holdout_json IS NOT NULL AND "
        "json_extract(holdout_json, '$.failed_round') = 1 AND "
        "json_extract(holdout_json, '$.generation') = ?", (jid, gen)).fetchone()[0]
    limit = cfg.data["holdout"]["max_failed_rounds"]
    if rounds < limit:
        return None
    conn.execute("UPDATE holdouts SET state='retired' WHERE job_id=? AND state='sealed' AND "
                 "generation=?", (jid, gen))
    worn = conn.execute("SELECT count(DISTINCT generation) FROM holdouts WHERE job_id=? AND "
                        "state='retired'", (jid,)).fetchone()[0]
    add_trail(conn, jid, actor, "holdout", f"holdout set {gen} worn after {rounds} failed "
              "round(s): retired; a fresh set must be sealed before the next claim",
              {"event": "worn", "generation": gen, "worn_sets": worn})
    if worn >= 2:
        add_trail(conn, jid, actor, "status", "blocked: a second holdout set is worn: the owner "
                  "decides (DECISION)")
        return "blocked"
    return None
