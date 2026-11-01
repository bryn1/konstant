"""The intake's deliverable, read and judged by code (docs/LEVEL5.md 4.2 step 3).

The planner writes OUT/BACKLOG.md (`B<n> | <type> | <title> | after:B<m>` per row, `-` for no
dependency) and one brief per row, OUT/jobs/B<n>.md. The DoD reviewer writes DOD-verdict.md (a
later cycle DOD-verdict-c<n>.md) with one line per job, `B<n> | SHIP|FIX | why`. `lint()` is the
whole deterministic filing rule set, used twice with the same inputs: by the DoD check of the
intake run (gate/rules/backlog.py: a refusal resumes the planner) and by the filing itself after
the check is MET (factory/intake.py: a refusal files nothing). Never raises for bad content.

  - BACKLOG.md exists and has at least one row; ids B1..Bn, unique; within the goal's max_jobs;
  - every type is a known task type, never a flag-only one (intake) and never `project`;
  - every `after:` names an EARLIER row (no cycles, no forward edges);
  - every brief exists, has a title and a DoD, and passes board/dod.py lint with NO flag (each DoD
    row settleable; NOPROBE = "DoD has no PROBE"), and no PROBE line the verifier's allowlist
    refuses (paths of the result as {workdir}/..., checked as a project path);
  - the newest DoD verdict file has a SHIP line for every row (only when `verdict=True`).
"""
from __future__ import annotations

import re
from pathlib import Path

ROW = re.compile(r"^\s*(B[1-9][0-9]*)\s*\|\s*([a-z][a-z0-9_-]*)\s*\|\s*(.+?)\s*\|\s*"
                 r"(after:\s*B[1-9][0-9]*|-)?\s*\|?\s*$")
VERDICT_ROW = re.compile(r"^\s*(B[1-9][0-9]*)\s*\|\s*(SHIP|FIX)\b\s*\|?\s*(.*)$", re.I)
VERDICT = "DOD-verdict.md"
MAX_TITLE = 200


def rows(out: Path) -> tuple:
    """([(bid, type, title, after_bid or None)], [reasons]) from OUT/BACKLOG.md."""
    f = Path(out) / "BACKLOG.md"
    if not f.is_file():
        return [], ["the planner wrote no OUT/BACKLOG.md"]
    found, reasons = [], []
    for ln in f.read_text(errors="replace").splitlines():
        s = ln.strip()
        if not s.startswith("B") or "|" not in s:
            continue
        m = ROW.match(s)
        if not m:
            reasons.append(f"BACKLOG.md: malformed row {s[:80]!r} (want `B<n> | <type> | "
                           "<title> | after:B<m>` or `-` for no dependency)")
            continue
        after = m.group(4)
        found.append((m.group(1), m.group(2), m.group(3).strip(),
                      after.split(":", 1)[1].strip() if after and after != "-" else None))
    if not found and not reasons:
        reasons.append("BACKLOG.md has no row (`B1 | <type> | <title> | -`)")
    return found, reasons


def brief_path(out: Path, bid: str) -> Path:
    return Path(out) / "jobs" / f"{bid}.md"


def title_of(brief: str, fallback: str) -> str:
    for ln in brief.splitlines():
        s = ln.strip().lstrip("#").strip()
        if s and not re.match(r"(?i)(dod|definition of done|acceptance)\s*[:\-]", s):
            return s[:MAX_TITLE]
    return fallback[:MAX_TITLE]


def verdicts(out: Path) -> dict:
    """{bid: (SHIP|FIX, why)} from the newest DOD-verdict file (highest -c<n>)."""
    files = sorted(Path(out).glob("DOD-verdict*.md"),
                   key=lambda p: int(re.search(r"-c(\d+)\.md$", p.name).group(1))
                   if re.search(r"-c(\d+)\.md$", p.name) else 1)
    found: dict = {}
    if files:
        for ln in files[-1].read_text(errors="replace").splitlines():
            m = VERDICT_ROW.match(ln)
            if m:
                found[m.group(1)] = (m.group(2).upper(), m.group(3).strip())
    return found


def lint(out: Path, cat, roots, max_jobs: int = 0, verdict: bool = True) -> tuple:
    """([reasons], [(bid, type, title, after, brief text)]): the filing rule set (module doc)."""
    from konstant.board import dod
    from konstant.verify import probe
    found, reasons = rows(out)
    ids = [r[0] for r in found]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        reasons.append(f"BACKLOG.md names {', '.join(dup)} twice")
    if max_jobs and len(found) > max_jobs:
        reasons.append(f"the backlog has {len(found)} jobs; the goal allows max_jobs = {max_jobs}")
    seen, jobs = set(), []
    votes = verdicts(out) if verdict else {}
    for bid, jtype, title, after in found:
        if jtype not in cat.types or cat.flag_only(jtype):
            reasons.append(f"job {bid} has type {jtype!r}: not a task type a job can have "
                           f"({', '.join(cat.classifiable())})")
        if after is not None and after not in seen:
            reasons.append(f"job {bid} runs after {after}, which is not an earlier row")
        seen.add(bid)
        bf = brief_path(out, bid)
        if not bf.is_file():
            reasons.append(f"job {bid} has no brief OUT/jobs/{bid}.md")
            continue
        brief = bf.read_text(errors="replace")
        if not dod.extract_acceptance(brief):
            reasons.append(f"job {bid} brief has no DoD section")
            continue
        for cls, row in dod.lint(brief):
            reasons.append(f"job {bid} DoD has no PROBE" if cls == "NOPROBE" else
                           f"job {bid} DoD row flagged {cls}: {row[:90]!r} - {dod.ADVICE[cls]}")
        for line in probe.probe_lines(brief):
            why = probe.check_line(probe.with_workdir(line, probe.LINT_WORKDIR), roots)
            if why:
                reasons.append(f"job {bid} PROBE refused: {line[:90]!r} - {why}")
        if verdict:
            word = votes.get(bid, (None, ""))[0]
            if word != "SHIP":
                reasons.append(f"job {bid} has no SHIP line in {VERDICT} (the DoD reviewer "
                               f"says {word or 'nothing'} about it)")
        jobs.append((bid, jtype, title_of(brief, title), after, brief))
    return reasons, jobs
