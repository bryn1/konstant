"""The verifier's door: POST /api/jobs/{ref}/verdict (DESIGN §4.2, §7).

The ONLY route that can write `verified`. Role: [board.policy] verify_roles (default verifier,
owner). The identity that closed the job can never post its verdict, whatever its role: the
closer cannot verify. Each verdict writes a `verifications` row and a `verdict` trail row.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from konstant.board import transitions
from konstant.board.api import holdouts
from konstant.board.api.deps import Actor, add_trail, set_status, writer
from konstant.board.api.lifecycle import run
from konstant.board.redact import redact, redact_obj
from konstant.board.transitions import Refused

router = APIRouter()


class VerdictIn(BaseModel):
    verdict: str
    reason: str = ""
    findings: list = []
    probes: Optional[list] = None
    rerun: Optional[dict] = None
    started_at: Optional[str] = None
    holdout: Optional[dict] = None      # verify/holdout.public(): ids, pass/fail, timings


@router.post("/api/jobs/{ref}/verdict")
def verdict(ref: str, body: VerdictIn, request: Request, actor: Actor = Depends(writer)):
    policy = request.app.state.policy

    def apply(conn, job):
        word = body.verdict.strip().upper()
        if word not in transitions.VERDICTS:
            raise Refused(422, f"verdict must be one of {', '.join(transitions.VERDICTS)}")
        if job["closed_by"] and actor.label == job["closed_by"]:
            raise Refused(403, f"the closer cannot verify: job {job['id']} was closed by "
                               f"{job['closed_by']}; a verdict must come from another identity")
        reason = redact(body.reason.strip())
        if word in ("FAIL", "BLOCKED") and not reason and not body.findings:
            raise Refused(422, f"a {word} verdict needs a reason or findings")
        if word == "PASS" and job["holdout_required"]:
            _holdouts_passed(conn, job, body.holdout, request.app.state.cfg)
        new_state, new_round = transitions.verdict_target(
            job["status"], word, job["verify_round"], policy.max_rounds)
        round_no = job["verify_round"] + 1
        conn.execute(
            "INSERT INTO verifications (job_id, round, actor, started_at, verdict, probes_json, "
            "rerun_json, holdout_json) VALUES (?,?,?,?,?,?,?,?)",
            (job["id"], round_no, actor.label, body.started_at, word,
             json.dumps(redact_obj(body.probes)) if body.probes is not None else None,
             json.dumps(redact_obj(body.rerun)) if body.rerun is not None else None,
             json.dumps(redact_obj(body.holdout)) if body.holdout is not None else None))
        add_trail(conn, job["id"], actor, "verdict", f"verdict {word} (round {round_no})"
                  + (f": {reason}" if reason else ""), {"verdict": word, "round": round_no})
        for finding in body.findings:
            add_trail(conn, job["id"], actor, "finding", str(finding))
        forced = holdouts.after_verdict(conn, job, actor, word, body.holdout,
                                        request.app.state.cfg)
        if forced and new_state == "queued":
            new_state = forced
        if new_state != job["status"] or new_round != job["verify_round"]:
            fields = {"verify_round": new_round}
            if new_state != "verified":
                fields["closed_by"] = None
            set_status(conn, job["id"], new_state, **fields)
        return {"verdict": word, "round": round_no}
    return run(request, ref, "verdict", actor, apply)


def _holdouts_passed(conn, job, holdout: dict | None, cfg) -> None:
    """A PASS on a holdout job needs the verifier's holdout result: at least min_per_job rows,
    every one passed, for exactly the sealed set's commitments, and no LEAK (LEVEL5 3.6 step 4;
    the ship guard repeats this in L5-4). Anything else is refused, whoever posts it."""
    from konstant.verify.holdout import digest
    sealed = [r for r in holdouts.listing(conn, job["id"]) if r["state"] == "sealed"]
    rows = (holdout or {}).get("rows") or []
    need = cfg.data["holdout"]["min_per_job"]
    ok = (holdout is not None and not holdout.get("leak") and len(sealed) >= need
          and len(rows) == len(sealed) and all(r.get("passed") is True for r in rows)
          and {r.get("hid") for r in rows} == {r["hid"] for r in sealed}
          and holdout.get("digest") == digest(sealed))
    if not ok:
        raise Refused(409, f"job {job['id']} has sealed holdouts: a PASS needs every one of them "
                           "run and passed on the closed commit (`konstant verify "
                           f"{job['id']}`), with the sealed set's commitment digest")
