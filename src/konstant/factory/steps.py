"""What the factory loop does next, read from the board (docs/LEVEL5.md 6.1). Pure decisions: this
module reads board records the loop fetched and returns actions; factory/loop.py runs them.

Every action is an idempotent board transition or a konstant step whose own guards hold, so a
factory killed at any point resumes from the board alone:

  approve   a filed goal job still waiting_approval (intake was cut off after the filing): the
            factory identity approves it (the board still wants the dod-review SHIP)
  intake    a goal with intake `none`, or `planning` with no intake running (cut off)
  author    a queued job whose holdout set was worn (retired) or never sealed by its writer:
            `holdout author` seals a fresh set before any claim (3.6 step 6)
  attempt   a queued (or claimed, after an UNMET or cut-off run) job, after its `after` job, with
            attempts left and no other job of its project in flight: `task run --job`, which
            claims, makes the clone, runs the phases and ends in close + verify
  verify    a completed_unverified job whose close was not followed by a verdict
  ship      a verified job without a standing ship (and no owner decision pending)
  exhaust   a job that used its max_attempts without reaching verified: blocked + BLOCKED
  escalate  a job or goal that needs the owner: blocked, a BLOCKED / LEAK verdict, a BLOCKED DoD
            check (DISPUTE: DECISION), a waiting owner-authored set (DECISION), an intake cut off
            while filing
Jobs of one project run serially: a project's next job starts only when no other job of it holds
a clone that is neither shipped nor escalated (a ship is always a fast-forward of the clone base).
"""
from __future__ import annotations

from dataclasses import dataclass, field

MODEL_STEPS = ("intake", "author", "attempt")       # count against [harness] max_concurrency
STEP_KINDS = MODEL_STEPS + ("verify", "ship")
STUCK_KINDS = ("BLOCKED", "LEAK", "HALTED", "ROLLBACK_FAILED", "DECISION")


@dataclass
class Action:
    kind: str
    goal: str
    job: int | None = None
    display_id: str = ""
    project: str = ""
    reason: str = ""
    event: str = ""                 # escalate: the event kind
    args: list = field(default_factory=list)

    def key(self) -> tuple:
        return (self.kind, self.goal, self.job)


def ship_of(job: dict, ships: list) -> dict | None:
    rows = [s for s in ships if s["job_id"] == job["id"] and s["state"] != "failed"]
    return rows[-1] if rows else None


def settled(job: dict, ships: list) -> bool:
    """Nothing more for the factory to do on this job (its ship stands, or ended)."""
    if job["status"] in ("cancelled", "reviewed"):
        return True
    s = ship_of(job, ships)
    return bool(s) and ((s["state"] == "shipped" and s.get("post") is not None)
                        or s["state"] in ("rolled_back", "rollback_failed"))


def done(job: dict, ships: list) -> bool:
    """Settled AND successful for its goal: shipped, cancelled, or rolled back with a follow-up
    job that carries the work on (a rollback without one ended in BLOCKED: max_rollbacks)."""
    if job["status"] in ("cancelled", "reviewed"):
        return True
    s = ship_of(job, ships)
    return bool(s) and ((s["state"] == "shipped" and s.get("post") is not None)
                        or (s["state"] == "rolled_back" and s.get("follow_up_id") is not None))


def open_kinds(job_id, escalations: list) -> set:
    return {e["kind"] for e in escalations if e["open"] and e.get("job_id") == job_id}


def last_close(job: dict) -> str:
    for t in reversed(job.get("trail") or []):
        if t["kind"] == "evidence" and (t.get("body") or "").startswith("closed by"):
            return t.get("ts") or ""
    return ""


def blocked_reason(job: dict) -> str:
    for t in reversed(job.get("trail") or []):
        if t["kind"] in ("status", "verdict", "budget") and t.get("body"):
            return t["body"]
    return f"job {job['display_id']} is blocked"


def dispute(run_dir: str) -> str:
    """The first DISPUTE row of the run's DONE.md ('' when none): an owner decision."""
    import json
    from pathlib import Path

    from konstant.gate.rules.done import cells
    try:
        rec = json.loads((Path(run_dir) / "record.json").read_text())
        text = (Path(rec["out"]) / "DONE.md").read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    for line in text.splitlines():
        cs = cells(line.strip()) if "|" in line and not line.strip().startswith("#") else []
        if cs and cs[0].strip("*`_ ").upper() == "DISPUTE":
            return ("holdout DISPUTE " + " | ".join(c.strip() for c in cs[1:3]))[:300]
    return ""


def approved_for(job: dict) -> bool:
    commit = ((job.get("evidence") or {}).get("commit") or "").strip()
    return bool(commit) and any(t["kind"] == "approval" and t.get("role") == "owner" and
                                (t.get("payload") or {}).get("ship_decision") == commit
                                for t in job.get("trail") or [])


class Planner:
    """One tick's view: goals (board serialised, with `view` = /api/factory/goals/{slug}), full
    job records, ships, open escalations, shipping state, running steps."""

    def __init__(self, goals, jobs, ships, escalations, shipping_halted, running, need, locked):
        self.goals, self.jobs, self.ships = goals, jobs, ships
        self.esc = escalations
        self.shipping_halted = shipping_halted
        self.running = running            # {(kind, goal, job)}
        self.need = need                  # job id -> holdouts needed
        self.locked = locked              # callable(job) -> True when its clone is locked
        self.state: dict = {}             # goal slug -> done | stuck | busy | paused
        self.projects: set = set()        # projects a running attempt / verify / ship works on

    def busy(self, job_id=None, kinds=None) -> bool:
        return any(j == job_id and (kinds is None or k in kinds) for k, _g, j in self.running)

    def occupied(self, project: str, me: int) -> bool:
        """A step runs on the project, or another job of it holds a clone that is neither
        settled nor escalated."""
        if project in self.projects:
            return True
        for j in self.jobs.values():
            if j["project"] != project or j["id"] == me or not j.get("workdir"):
                continue
            if settled(j, self.ships) or open_kinds(j["id"], self.esc) & set(STUCK_KINDS):
                continue
            if j["status"] in ("blocked", "cancelled"):
                continue
            return True
        return False

    def shipped(self, jid, depth: int = 0) -> bool:
        """The work of job `jid` stands on the target: its ship stands, or it was rolled back
        and its follow-up job's work stands (a job `after` it builds on that, never on code a
        rollback took out again)."""
        j = self.jobs.get(jid)
        if j is None or depth > 20:
            return False
        s = ship_of(j, self.ships)
        if s and s["state"] == "shipped" and s.get("post") is not None:
            return True
        if s and s["state"] == "rolled_back" and s.get("follow_up_id"):
            return self.shipped(s["follow_up_id"], depth + 1)
        return False

    def goal_actions(self, g: dict) -> list:
        slug = g["slug"]
        if g["status"] != "active":
            self.state[slug] = "done" if g["status"] == "done" else "paused"
            return []
        goal_open = {e["kind"] for e in self.esc if e["open"] and e.get("goal") == slug
                     and not e.get("job_id")}
        if any(k == slug for _k, k, _j in self.running if _k == "intake"):
            self.state[slug] = "busy"
            return []
        if g["intake"] in ("none", "planning"):
            self.state[slug] = "busy"
            return [Action("intake", slug, reason="take the goal in")]
        if g["intake"] in ("filing", "refused"):
            self.state[slug] = "stuck"
            if "BLOCKED" in goal_open:
                return []
            why = ("intake was cut off while filing: the owner checks the filed jobs"
                   if g["intake"] == "filing" else "intake refused: nothing filed")
            return [Action("escalate", slug, event="BLOCKED", reason=why)]
        acts, states = [], []
        mine = [j for j in self.jobs.values() if j.get("goal_id") == g["id"]]
        for j in sorted(mine, key=lambda x: x["id"]):
            st, act = self.job_action(g, j)
            states.append(st)
            if act is not None:
                acts.append(act)
        if mine and all(s == "done" for s in states):
            self.state[slug] = "done"
            return [Action("done", slug, reason=f"{len(mine)} job(s) shipped")]
        self.state[slug] = "busy" if any(s in ("busy", "ready") for s in states) else "stuck"
        return acts

    def job_action(self, g: dict, j: dict) -> tuple:
        """(state, action|None); state: done | busy | ready | stuck | waiting."""
        slug, jid, st = g["slug"], j["id"], j["status"]
        mk = lambda kind, **kw: Action(kind, slug, jid, j["display_id"], j["project"], **kw)  # noqa: E731
        if settled(j, self.ships):
            return ("done" if done(j, self.ships) else "stuck"), None
        if self.busy(jid):
            return "busy", None
        kinds = open_kinds(jid, self.esc)
        if st == "waiting_approval":
            return "ready", mk("approve", reason="filed, not yet approved")
        if st == "verified":
            s = ship_of(j, self.ships)
            if s is not None:                       # in flight: reconcile.py settles it
                return "busy", None
            if self.shipping_halted:
                return "stuck", None
            if kinds & set(STUCK_KINDS) and not ("DECISION" in kinds and approved_for(j)):
                return "stuck", None
            return "ready", mk("ship", reason="verified")
        if kinds & {"BLOCKED", "LEAK", "HALTED", "ROLLBACK_FAILED"}:
            return "stuck", None
        if st == "blocked":
            text = blocked_reason(j)
            ev = "DECISION" if "DECISION" in text or "DISPUTE" in text else "BLOCKED"
            if ev in kinds:
                return "stuck", None
            return "stuck", mk("escalate", event=ev, reason=text)
        if st == "completed_unverified":
            vers = j.get("verifications") or []
            last = vers[-1] if vers else None
            if last and last["verdict"] == "BLOCKED" and last.get("finished_at", "") >= \
                    last_close(j):
                hold = last.get("holdouts") or {}
                ev = "LEAK" if hold.get("leak") else "BLOCKED"
                why = "; ".join(hold.get("reasons") or []) or "the verifier answered BLOCKED"
                return "stuck", mk("escalate", event=ev, reason=f"verify BLOCKED: {why}")
            return "ready", mk("verify", reason="closed, no verdict yet")
        if st not in ("queued", "claimed"):
            return "stuck", None
        after = j.get("after_id")
        if after and not self.shipped(after):
            a = self.jobs.get(after)
            blocked = a is not None and ("stuck" == self.job_action(g, a)[0])
            return ("stuck" if blocked else "waiting"), None
        runs = j.get("runs") or []
        if st == "claimed" and runs and runs[-1].get("result") == "BLOCKED":
            why = dispute(runs[-1]["run_dir"])     # never resolves by another attempt (3.6)
            if why:
                if "DECISION" in kinds:
                    return "stuck", None
                return "stuck", mk("escalate", event="DECISION", reason=why)
            # any other BLOCKED check (a verdict FAIL at the cycle cap, ...) was a failed
            # attempt: the next attempt may fix it, max_attempts bounds it
        sealed = sum(1 for h in j.get("holdouts") or [] if h["state"] == "sealed")
        if j.get("holdout_required") and sealed < self.need.get(jid, 1):
            if g["spec"]["holdout"]["author"] == "owner":
                if "DECISION" in kinds:
                    return "stuck", None
                return "stuck", mk("escalate", event="DECISION", reason="the job waits for the "
                                   "owner's holdout scenarios (`konstant holdout add`)")
            return "ready", mk("author", reason="no sealed holdout set (worn or never sealed)")
        b = (g.get("view") or {}).get("jobs") or []
        mine = next((x for x in b if x["id"] == jid), None)
        if mine and mine["max_attempts"] and mine["attempts"] >= mine["max_attempts"]:
            return "stuck", mk("exhaust", reason=f"{mine['attempts']} of {mine['max_attempts']} "
                               "attempts used without reaching verified")
        if self.occupied(j["project"], jid) or (st == "claimed" and self.locked(j)):
            return "waiting", None
        return "ready", mk("attempt", reason=f"attempt {(mine or {}).get('attempts', 0) + 1}")
