"""Definition of Done in a job brief: extraction (a hard requirement) and row lint (warnings).

A job is filed with a brief; the board lifts its acceptance from the first `DoD:` /
`Definition of Done:` / `Acceptance:` / `Acceptance criteria:` line (a markdown heading or bullet
prefix is allowed) to the end of the brief. No such line = no job: a job whose "done" is unstated
is how a report comes to satisfy a build. The acceptance text is immutable after insert.

The lint flags DoD rows that nothing a verifier reads can ever settle (a filing-time row
lint; an earlier version of it measured ~0.9 precision - too noisy to refuse, so it warns):
  NEG         a constraint about what the worker did NOT do ("never spawn", "do not touch")
  LIVE        live state (deployed, pushed, is active, an HTTP answer) with no PROBE on the row
              or the line right under it
  VISUAL      "looks right" / screenshot rows with no measured value
  CONSTRAINT  a "- no/never/do not ..." bullet under the DoD line: constraints go above it
  NOPROBE     the DoD carries no PROBE line at all: `konstant verify` passes a job only on a
              matched DoD probe, so such a job can only end BLOCKED there (REVIEW F-02; a
              review-type job closed by `job review` does not need one)
"""
from __future__ import annotations

import re

DOD_HEAD = re.compile(r"(?im)^[ \t>#*-]*(?:DoD|Definition of Done|Acceptance(?: criteria)?)"
                      r"\s*[:\-]")
_BUL = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)]|\(\w{1,2}\)|[a-z]\))\s+")
_HEAD_STRIP = re.compile(r"(?i)^[>#*-]*\s*(?:DoD|Definition of Done|Acceptance(?: criteria)?)"
                         r"\s*[:\-]?\s*")

NEG = re.compile(
    r"(?i)\b(?:never|do\s+not|don't|must\s+not|did\s+not|didn't|without)\s+(?:\w+\s+){0,2}?"
    r"(?:spawn\w*|subagents?|workflows?|use|using|call|calling|edit|modify|touch|push|restart\w*|"
    r"print|commit|write|copy|reuse|weaken|disturb|rewrite|author|merge|open|ask|delegate|browse)\b"
    r"|\bLEAF\b|\btime-?box\b|\bno\s+spawn\w*|\bno\s+subagents?\b")
NEG_LIVE = re.compile(r"(?i)\b(?:not|never|nothing|no)\s+(?:\w+\s+){0,2}?"
                      r"(?:pushed|merged|restarted|deployed|installed)\b")
DIFF_SCOPED = re.compile(r"(?i)(?:touch|modify|edit|rewrite|write)\s+(?:any\s+|the\s+)?[\w.-]+/")
LIVE = re.compile(
    r"(?i)\b(?:deployed|(?:is|are|was|were|be|been|now|gets?|got)\s+(?:re-?)?installed|"
    r"(?:re-?)?installed\s+(?:to|on|at|in|with|as|live)|"
    r"is\s+(?:active|running|enabled|live|serving)|active\s+(?:again|after)|"
    r"restarted|pushed|origin/(?:main|master)|on\s+origin/[\w.-]+|"
    r"cron\s+line\s+(?:installed|present|added)|"
    r"systemctl\s+(?:--user\s+)?(?:show|is-active|is-enabled|status)\s+(?!only\b)[\w@.-]+|"
    r"daemon-reload|live\s+(?:on|at)|timer\s+active|service\s+(?:live|active|running)|"
    r"curl\b[^;]{0,120}?\b(?:returns?|answers?)\s+(?:HTTP\s*)?\d{3})")
VISUAL = re.compile(
    r"(?i)\b(?:looks?\s+(?:right|good|correct|clean|fine|nice|intentional)|visually|"
    r"screenshots?\s+(?:seen|attached|evidence)|\(screenshot\)|with\s+screenshots?|"
    r"renders?\s+(?:correctly|properly|fine|cleanly|well)|eyeball\w*)\b")
MEASURE = re.compile(r"(?i)(=\s*-?\d|overflow|console_errors|scrollWidth|contrast\s+ratio|"
                     r"exit\s+0|\bJSON\b|\bPASS\b)")
CONSTRAINT = re.compile(r"(?i)^-\s*(?:no|never|do not|don't|nothing|without)\b")


def extract_acceptance(brief: str) -> str:
    """The brief from its first DoD/Acceptance line to the end, or '' when there is none."""
    if not isinstance(brief, str):
        return ""
    m = DOD_HEAD.search(brief)
    if not m:
        return ""
    line_start = brief.rfind("\n", 0, m.start()) + 1
    text = brief[line_start:].strip()
    first, _, rest = text.partition("\n")
    if not _HEAD_STRIP.sub("", first.strip()).strip() and not rest.strip():
        return ""                                   # a bare "DoD:" with nothing after it
    return text


def _rows(acceptance: str) -> list:
    lines = []
    for ln in acceptance.splitlines():
        s = ln.strip()
        if not s:
            continue
        if (_BUL.match(ln) or not lines or DOD_HEAD.match(ln)
                or s.startswith(("PROBE", "VERIFY_CMD"))):
            lines.append(s)
        else:
            lines[-1] += " " + s                   # a wrapped line continues its row
    rows = []
    for r in lines:
        r = _HEAD_STRIP.sub("", r)
        rows += [p.strip() for p in re.split(r";\s+|\s(?=\(\d{1,2}\)\s)", r) if p.strip()]
    return rows


def dod_rows(acceptance: str) -> list:
    """The deliverable rows of a DoD, in order: what a run's DONE.md answers as DoD-1, DoD-2 ...
    PROBE and VERIFY_CMD lines are the verifier's, not rows."""
    rows = [" ".join(_BUL.sub("", r, count=1).split()) for r in _rows(acceptance or "")]
    return [r for r in rows if not r.startswith(("PROBE", "VERIFY_CMD"))
            and re.search(r"[A-Za-z0-9]", r)]


def lint(brief: str) -> list:
    """[(CLASS, row excerpt)] for each DoD row a verifier cannot settle. Never raises."""
    acceptance = extract_acceptance(brief)
    out = []
    if acceptance and not re.search(r"(?m)^[ \t>*-]*PROBE:", acceptance):
        rows = dod_rows(acceptance)
        out.append(("NOPROBE", (rows[0] if rows else acceptance)[:170]))
    for ln in acceptance.splitlines()[1:]:
        s = ln.strip()
        if CONSTRAINT.match(s) and "PROBE" not in s:
            out.append(("CONSTRAINT", s[:170]))
    rows = _rows(acceptance)
    for i, r in enumerate(rows):
        if "PROBE" in r:
            continue
        nxt = rows[i + 1] if i + 1 < len(rows) else ""
        r = " ".join(_BUL.sub("", r, count=1).split())
        neg = NEG_LIVE.search(r) or next(
            (m for m in NEG.finditer(r)
             if not DIFF_SCOPED.match(r, m.end() - len(m.group(0).split()[-1]))), None)
        if neg:
            out.append(("NEG", r[:170]))
        if VISUAL.search(r) and not MEASURE.search(r):
            out.append(("VISUAL", r[:170]))
        live = LIVE.search(NEG_LIVE.sub(lambda m: " " * len(m.group(0)), r))
        if live and not nxt.startswith("PROBE"):
            out.append(("LIVE", r[:170]))
    return out


ADVICE = {
    "NEG": "a verifier cannot show what was NOT done; move constraints above the DoD line, or "
           "state something checkable (e.g. 'the diff touches only app/x.py')",
    "LIVE": "live state is settled only by a read-back: put a line "
            "'PROBE: <read-only command> => <regex>' right under the row (the verifier reads "
            "PROBE lines that start a line)",
    "VISUAL": "nothing is measured: name the measured value instead of how it looks",
    "CONSTRAINT": "constraint rows go above the DoD line; under it every row is a deliverable",
    "NOPROBE": "the DoD has no PROBE line, so `konstant verify` can only settle BLOCKED: add "
               "'PROBE: <read-only command> => <regex>' (a review-type job closed by `job review` "
               "needs none)",
}
