"""Rule `verified`: a job this run is bound to (`--job`) that was closed has a `konstant verify`
verdict newer than the run start. Latest verdict FAIL = UNMET, BLOCKED = BLOCKED, PASS = met; a
closed job with no verdict since the start = UNMET. A job still open adds nothing (the runner
closes it after MET). A board that cannot be read is UNMET by name (start the board)."""
from __future__ import annotations

import calendar
import time

from konstant.gate.rules.common import Finding, Run




def _epoch(ts: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return 0.0


def check(run: Run) -> list:
    jid = run.rec.get("job")
    if not jid:
        return []
    if run.offline:
        return [Finding("verified", f"offline check: job {jid}'s konstant verify verdict was not "
                                    "read", severity="warn")]
    if run.board is None:
        return [Finding("verified", f"job {jid}: no board configured to read its verdict")]
    try:
        job = run.board.job(jid)
    except Exception as exc:  # unreachable board: fail closed
        return [Finding("verified", f"job {jid}: cannot read it from the board ({exc})")]
    if job is None:
        return [Finding("verified", f"job {jid} does not exist on the board")]
    since = int(run.start)
    fresh = [v for v in job.get("verifications") or [] if _epoch(v.get("finished_at")) >= since]
    if fresh:
        last = max(fresh, key=lambda v: (v.get("round", 0), v.get("id", 0)))
        word = last.get("verdict")
        if word == "PASS":
            return []
        if word == "BLOCKED":
            return [Finding("verified", f"job {jid}: konstant verify says BLOCKED (round "
                                        f"{last.get('round')})", severity="blocked")]
        return [Finding("verified", f"job {jid}: konstant verify says {word} (round "
                                    f"{last.get('round')}) - fix the findings on its trail",
                        owner="producer")]
    if job.get("status") == "completed_unverified":
        return [Finding("verified", f"job {jid} was closed but has no konstant verify verdict "
                                    f"since the run started: run `konstant verify {jid}`")]
    return []
