"""The job state machine as ONE table (DESIGN §4.2). Every write route asks `decide()`.

Order of refusal: the role first (403 naming the roles that may), then the state (409 naming the
current state and the verbs that are legal from it), then the verb's own guard in the route.
No verb writes `verified` except a verifier verdict, and `verified`/`reviewed` cannot be left
(a DB trigger holds the second rule too).
"""
from __future__ import annotations

from dataclasses import dataclass

STATES = ("queued", "waiting_approval", "claimed", "blocked", "completed_unverified",
          "verified", "reviewed", "cancelled")
TERMINAL = ("verified", "reviewed")
OPEN = ("queued", "waiting_approval", "claimed", "blocked", "completed_unverified")
VERDICTS = ("PASS", "FAIL", "BLOCKED")


@dataclass(frozen=True)
class Rule:
    verb: str
    sources: tuple          # states the verb is legal from
    target: str             # resulting state; "" = decided by the verb (verdict) or unchanged
    roles: object           # a tuple of roles, or the name of a [board.policy] role set
    guard: str


TABLE = (
    Rule("add", (), "queued", ("owner", "orchestrator", "worker"),
         "acceptance with a DoD line; type known; depth <= 2; --approval -> waiting_approval"),
    Rule("approve", ("waiting_approval",), "queued", "approve_roles",
         "not the requester's own label; a goal job: a dod-review SHIP from another identity "
         "first, and the factory identity may approve it"),
    Rule("claim", ("queued", "blocked"), "claimed", ("orchestrator", "worker"),
         "not a factory identity, the job's DoD reviewer or scenario writer, or the planner of "
         "a goal job; after_id, if set, is verified or "
         "reviewed; a holdout job: enough sealed holdouts, and the first claim records its clone"),
    Rule("block", ("claimed",), "blocked", ("owner", "orchestrator", "worker"), "reason required"),
    Rule("close", ("claimed",), "completed_unverified", ("owner", "orchestrator", "worker"),
         "not a factory identity, the job's DoD reviewer or scenario writer, or the planner of "
         "a goal job; requester or assignee (or owner); the "
         "evidence contract"),
    Rule("review", ("claimed", "completed_unverified"), "reviewed", "review_roles",
         "type in review_types; not the requester, assignee or closer; a SHIP/PASS verdict and "
         "a DONE.md"),
    Rule("verdict", ("completed_unverified",), "", "verify_roles",
         "the closer cannot verify; PASS -> verified, FAIL -> queued or blocked at max_rounds, "
         "BLOCKED -> unchanged"),
    Rule("reopen", ("completed_unverified", "blocked", "cancelled"), "queued", "reopen_roles",
         "reason required"),
    Rule("cancel", OPEN, "cancelled", ("owner", "orchestrator"), "reason required"),
    Rule("move", STATES, "", ("owner", "orchestrator"), "target depth valid"),
)
RULES = {r.verb: r for r in TABLE}
VERBS = tuple(r.verb for r in TABLE if r.verb != "add")


class Refused(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def roles_for(verb: str, policy) -> tuple:
    roles = RULES[verb].roles
    return policy.roles(roles) if isinstance(roles, str) else roles


def legal_verbs(state: str) -> list:
    return [r.verb for r in TABLE if state in r.sources]


def check_role(verb: str, role: str, policy, extra: tuple = ()) -> None:
    allowed = roles_for(verb, policy) + tuple(r for r in extra if r not in roles_for(verb, policy))
    if role not in allowed:
        raise Refused(403, f"{verb} requires role {', '.join(allowed)} (this token is {role})")


def decide(state: str, verb: str, role: str, policy, extra: tuple = ()) -> Rule:
    """The rule for (state, verb, role), or Refused(403|409). `extra`: roles the route admits
    for this actor besides the rule's (the factory identity approving a goal job, LEVEL5 4.2)."""
    rule = RULES[verb]
    check_role(verb, role, policy, extra)
    if state not in rule.sources:
        legal = ", ".join(legal_verbs(state)) or "none"
        raise Refused(409, f"illegal transition: the job is {state}; {verb} is not legal from "
                           f"{state} (legal verbs: {legal})")
    return rule


def verdict_target(state: str, verdict: str, verify_round: int, max_rounds: int) -> tuple:
    """-> (new state, new verify_round) for a verifier verdict on a completed_unverified job."""
    if verdict == "PASS":
        return "verified", verify_round
    if verdict == "FAIL":
        nxt = verify_round + 1
        return ("blocked" if nxt >= max_rounds else "queued"), nxt
    return state, verify_round
