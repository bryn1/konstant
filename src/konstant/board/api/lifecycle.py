"""Lifecycle verbs on one job: claim, block, close, review, reopen, cancel, move, approve.

Each route runs inside one transaction: load the job, ask transitions.decide() (role, then
state), check the verb's own guard, write the row and ONE trail entry. Any refusal rolls the
whole write back.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from konstant.board import db, evidence, transitions, tree
from konstant.board.api.deps import (Actor, add_trail, load_job, refuse, serialize, set_status,
                                     writer)
from konstant.board.redact import redact, redact_obj
from konstant.board.transitions import Refused

router = APIRouter()
VERDICT_LINE = re.compile(r"^#\s*VERDICT:\s*([A-Za-z]+)\b", re.M)


class Reason(BaseModel):
    reason: str = ""


class CloseIn(BaseModel):
    verify_cmd: Optional[str] = None
    verify_exit: Optional[object] = None
    verify_output: Optional[str] = None
    control_cmd: Optional[str] = None
    control_exit: Optional[object] = None
    commit: Optional[str] = None
    base: Optional[str] = None
    probes: list = []
    docs: Optional[str] = None
    evidence_path: Optional[str] = None
    result_summary: Optional[str] = None


class ReviewIn(BaseModel):
    verdict: str = ""
    done: str = ""
    verdict_path: str = ""
    done_path: str = ""


class MoveIn(BaseModel):
    parent: str
    reason: str = ""


def run(request: Request, ref: str, verb: str, actor: Actor, apply) -> dict:
    """Shared frame: transaction, root refusal, decide(), the verb's apply(conn, job) -> extra."""
    with db.transaction(request.app.state.db_path) as conn:
        job = load_job(conn, ref)
        if job["parent_id"] is None:
            raise HTTPException(409, f"job {job['id']} is a project root; a root never changes "
                                     "state and is never moved")
        try:
            transitions.decide(job["status"], verb, actor.role, request.app.state.policy)
            extra = apply(conn, job) or {}
        except (Refused, tree.TreeRefused) as exc:
            refuse(exc)
        out = serialize(conn, conn.execute("SELECT * FROM jobs WHERE id=?",
                                           (job["id"],)).fetchone())
    out.update(extra)
    return out


def _need_reason(text: str, verb: str) -> str:
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, f"{verb} needs a reason")
    return redact(text)


@router.post("/api/jobs/{ref}/claim")
def claim(ref: str, request: Request, actor: Actor = Depends(writer)):
    def apply(conn, job):
        if job["after_id"] is not None:
            dep = conn.execute("SELECT status FROM jobs WHERE id=?", (job["after_id"],)).fetchone()
            if dep is None or dep["status"] not in transitions.TERMINAL:
                state = dep["status"] if dep else "missing"
                raise Refused(409, f"job {job['id']} runs after job {job['after_id']}, which "
                                   f"is {state}; it must be verified or reviewed first")
        set_status(conn, job["id"], "claimed", assignee=actor.label)
        add_trail(conn, job["id"], actor, "status", f"claimed by {actor.label}")
    return run(request, ref, "claim", actor, apply)


@router.post("/api/jobs/{ref}/block")
def block(ref: str, body: Reason, request: Request, actor: Actor = Depends(writer)):
    def apply(conn, job):
        reason = _need_reason(body.reason, "block")
        set_status(conn, job["id"], "blocked")
        add_trail(conn, job["id"], actor, "status", f"blocked: {reason}")
    return run(request, ref, "block", actor, apply)


@router.post("/api/jobs/{ref}/close")
def close(ref: str, body: CloseIn, request: Request, actor: Actor = Depends(writer)):
    policy = request.app.state.policy

    def apply(conn, job):
        if actor.role != "owner" and actor.label not in (job["requested_by"], job["assignee"]):
            raise Refused(403, f"only the requester ({job['requested_by']}), the assignee "
                               f"({job['assignee'] or 'none'}) or an owner may close job "
                               f"{job['id']}")
        payload = redact_obj(body.model_dump(exclude_none=True))
        refusals, warnings, record = evidence.check_close(payload, policy)
        if refusals:
            raise Refused(422, "close refused - evidence contract: " + "; ".join(refusals))
        summary = (body.result_summary or record.get("verify_output", ""))[:300]
        set_status(conn, job["id"], "completed_unverified", closed_by=actor.label,
                   evidence_json=json.dumps(record), result_summary=redact(summary))
        add_trail(conn, job["id"], actor, "evidence", f"closed by {actor.label}",
                  {"warnings": warnings, "self_attested": record["self_attested"]})
        return {"warnings": warnings}
    return run(request, ref, "close", actor, apply)


@router.post("/api/jobs/{ref}/review")
def review(ref: str, body: ReviewIn, request: Request, actor: Actor = Depends(writer)):
    catalog = request.app.state.catalog

    def apply(conn, job):
        own = {job["requested_by"], job["assignee"], job["closed_by"]} - {None}
        if actor.label in own:
            raise Refused(403, f"a review comes from another identity: {actor.label} filed, "
                               f"claimed or closed job {job['id']}, and nobody reviews their "
                               "own work (as the closer cannot verify it)")
        if not catalog.is_review_type(job["type"]):
            raise Refused(409, f"job {job['id']} is type {job['type']}; only "
                               f"{', '.join(catalog.review_types)} close by review - other "
                               "types close with `job close` and are verified")
        words = VERDICT_LINE.findall(body.verdict or "")
        if not words:
            raise Refused(422, "the verdict carries no '# VERDICT: SHIP|PASS' line")
        word = words[-1].upper()
        if word not in ("SHIP", "PASS"):
            raise Refused(422, f"the verdict is {word}; only SHIP or PASS closes a review job - "
                               "fix the findings (or block the job), then re-judge")
        if not (body.done or "").strip():
            raise Refused(422, "a DONE.md is required (--done FILE) and it is empty")
        sha = {k: hashlib.sha256(getattr(body, k).encode()).hexdigest() for k in ("verdict", "done")}
        set_status(conn, job["id"], "reviewed", closed_by=job["closed_by"] or actor.label)
        add_trail(conn, job["id"], actor, "review", f"reviewed: verdict {word}",
                  {"verdict": word, "verdict_path": body.verdict_path, "done_path": body.done_path,
                   "verdict_sha256": sha["verdict"], "done_sha256": sha["done"],
                   "done": redact(body.done[:4000])})
    return run(request, ref, "review", actor, apply)


@router.post("/api/jobs/{ref}/reopen")
def reopen(ref: str, body: Reason, request: Request, actor: Actor = Depends(writer)):
    def apply(conn, job):
        reason = _need_reason(body.reason, "reopen")
        set_status(conn, job["id"], "queued", closed_by=None)
        add_trail(conn, job["id"], actor, "status", f"reopened from {job['status']}: {reason}")
    return run(request, ref, "reopen", actor, apply)


@router.post("/api/jobs/{ref}/cancel")
def cancel(ref: str, body: Reason, request: Request, actor: Actor = Depends(writer)):
    def apply(conn, job):
        reason = _need_reason(body.reason, "cancel")
        set_status(conn, job["id"], "cancelled")
        add_trail(conn, job["id"], actor, "status", f"cancelled: {reason}")
    return run(request, ref, "cancel", actor, apply)


@router.post("/api/jobs/{ref}/approve")
def approve(ref: str, request: Request, actor: Actor = Depends(writer)):
    def apply(conn, job):
        set_status(conn, job["id"], "queued")
        add_trail(conn, job["id"], actor, "approval", f"approved by {actor.label}")
    return run(request, ref, "approve", actor, apply)


@router.post("/api/jobs/{ref}/move")
def move(ref: str, body: MoveIn, request: Request, actor: Actor = Depends(writer)):
    def apply(conn, job):
        target = tree.resolve_path(conn, body.parent)
        if target is None:
            raise HTTPException(404, f"parent {body.parent} not found")
        plan = tree.validate_move(conn, job["id"], target)
        if plan["noop"]:
            return {"noop": True, "shifted": []}
        reason = _need_reason(body.reason, "move")
        ids = tree.affected(conn, job["id"], (plan["from_parent_id"], target))
        before = {i: tree.display_id(conn, i) for i in ids}
        conn.execute("UPDATE jobs SET parent_id=? WHERE id=?", (target, job["id"]))
        after = {i: tree.display_id(conn, i) for i in ids}
        shifted = [{"id": i, "from": before[i], "to": after[i]} for i in sorted(ids)
                   if before[i] != after[i] and i != job["id"]]
        add_trail(conn, job["id"], actor, "move",
                  f"moved: {before[job['id']]} -> {after[job['id']]}: {reason}",
                  {"from_parent_id": plan["from_parent_id"], "to_parent_id": target,
                   "shifted": shifted})
        return {"noop": False, "shifted": shifted}
    return run(request, ref, "move", actor, apply)
