"""The intake card on a job (wave L5-T; docs/CONCEPTS.md "Triage", konstant/triage/card.py).

  POST /api/jobs/{ref}/intake-card  {card, run}   record the card a run computed (owner,
                                                   orchestrator: the gate and the runner; never a
                                                   phase, whose role is worker)
  GET  /api/jobs/{ref}/intake-cards               every card of the job, oldest first (readers)

Append-only (table intake_cards, migration 0006). The board recomputes the card's sha256, checks
its shape (tier, continuation, research flag) and writes one `note` trail row with the card's
one-line summary. `job show` lists the cards too.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from konstant.board import db
from konstant.board.api.deps import Actor, add_trail, load_job, reader, writer
from konstant.board.redact import redact_obj

router = APIRouter()
CARD_ROLES = ("owner", "orchestrator")
MAX_CARD = 64 * 1024
TIERS = ("inline", "agent", "fanout", "max", "factory")


class CardIn(BaseModel):
    card: dict
    run: str = Field(default="", max_length=300)


def check_card(card: dict) -> None:
    tier = (card.get("tier") or {}).get("name") if isinstance(card.get("tier"), dict) else None
    if tier not in TIERS:
        raise HTTPException(422, f"card.tier.name must be one of {', '.join(TIERS)}")
    if card.get("continuation") not in ("new", "continuation"):
        raise HTTPException(422, "card.continuation must be new or continuation")
    if not isinstance(card.get("research_required"), bool):
        raise HTTPException(422, "card.research_required must be true or false")
    if len(json.dumps(card)) > MAX_CARD:
        raise HTTPException(413, f"an intake card is at most {MAX_CARD} bytes")


def digest(card: dict) -> str:
    body = {k: v for k, v in card.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def listing(conn, job_id: int) -> list:
    out = []
    for r in conn.execute("SELECT id, run, actor, tier, continuation, research_required, "
                          "card_json, sha256, at FROM intake_cards WHERE job_id=? ORDER BY id",
                          (job_id,)).fetchall():
        d = dict(r)
        d["card"] = json.loads(d.pop("card_json"))
        d["research_required"] = bool(d["research_required"])
        out.append(d)
    return out


@router.post("/api/jobs/{ref}/intake-card")
def add_card(ref: str, body: CardIn, request: Request, actor: Actor = Depends(writer)):
    if actor.role not in CARD_ROLES:
        raise HTTPException(403, "an intake card is recorded by the gate or the runner (owner, "
                                 "orchestrator), never by a phase")
    card = redact_obj(body.card)
    check_card(card)
    sha = digest(card)
    card["sha256"] = sha
    from konstant.triage.card import summary
    with db.transaction(request.app.state.db_path) as conn:
        job = load_job(conn, ref)
        cid = conn.execute(
            "INSERT INTO intake_cards (job_id, run, actor, role, tier, continuation, "
            "research_required, card_json, sha256) VALUES (?,?,?,?,?,?,?,?,?)",
            (job["id"], body.run or None, actor.label, actor.role, card["tier"]["name"],
             card["continuation"], int(card["research_required"]),
             json.dumps(card, sort_keys=True), sha)).lastrowid
        try:
            line = summary(card)
        except (KeyError, TypeError):
            line = f"intake card: tier {card['tier']['name']} (sha256 {sha[:12]})"
        add_trail(conn, job["id"], actor, "note", line)
    return {"job_id": job["id"], "card_id": cid, "sha256": sha}


@router.get("/api/jobs/{ref}/intake-cards")
def get_cards(ref: str, request: Request, actor: Actor = Depends(reader)):
    with db.reading(request.app.state.db_path) as conn:
        return {"cards": listing(conn, load_job(conn, ref)["id"])}
