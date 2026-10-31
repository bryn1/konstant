"""Rule `holdouts` (docs/LEVEL5.md 3.6 step 7). UNEXCUSABLE: a DECLINED row never waives it.

- The verifier's holdout result for the run's job (the newest verdict since the run started):
  each failed holdout is UNMET `holdout H<n> failed (hint: ...)` (owner producer); a LEAK or a
  commitment mismatch is BLOCKED. Only ids and hints are on the board, never a scenario.
- DISPUTE: a producer that believes a holdout contradicts the DoD writes
  `DISPUTE | H<n> | <why>` in DONE.md. A dispute never resolves automatically: it is BLOCKED (an
  owner decision, the run stops with the reason written down) and it excuses nothing. A
  malformed DISPUTE row is UNMET.
"""
from __future__ import annotations

import re

from konstant.gate.rules.common import Finding, Run
from konstant.gate.rules.done import cells
from konstant.gate.rules.verified import _epoch

_HID = re.compile(r"^H[1-9][0-9]*$")


def disputes(run: Run) -> list:
    try:
        text = (run.out / "DONE.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if "|" not in line or line.startswith("#"):
            continue
        cs = cells(line)
        if not cs or cs[0].strip("*`_ ").upper() != "DISPUTE":
            continue
        hid = cs[1].strip("*`_ ") if len(cs) > 1 else ""
        why = " | ".join(cs[2:]).strip()
        if not _HID.match(hid) or len(re.findall(r"[A-Za-z0-9]+", why)) < 3:
            out.append(Finding("holdouts", "DONE.md DISPUTE row needs `DISPUTE | H<n> | <why "
                                           "the holdout contradicts the DoD>`"))
        else:
            out.append(Finding("holdouts", f"DISPUTE: {hid} - {why[:160]} - a holdout dispute "
                                           "is an owner decision; it never resolves "
                                           "automatically", owner="none", severity="blocked"))
    return out


def verifier(run: Run) -> list:
    jid = run.rec.get("job")
    if not jid or run.offline or run.board is None:
        return []
    try:
        job = run.board.job(jid)
    except Exception:          # the `verified` rule reports an unreadable board
        return []
    since = int(run.start)
    fresh = [v for v in (job or {}).get("verifications") or []
             if _epoch(v.get("finished_at")) >= since and v.get("holdouts")]
    if not fresh:
        return []
    h = max(fresh, key=lambda v: (v.get("round", 0), v.get("id", 0)))["holdouts"]
    if h.get("leak") or h.get("mismatch"):
        what = "a canary leaked" if h.get("leak") else "the store changed after sealing"
        return [Finding("holdouts", f"job {jid}: holdouts BLOCKED: {what} (see the verdict on "
                                    "its trail)", owner="none", severity="blocked")]
    return [Finding("holdouts", f"holdout {r['hid']} failed (hint: {r.get('hint', '-')})",
                    owner="producer")
            for r in h.get("rows") or [] if r.get("passed") is False]


def check(run: Run) -> list:
    return verifier(run) + disputes(run)
