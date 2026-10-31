"""Rules `verdicts` and `phases` (DESIGN §6.4).

verdicts: every fresh verdict file (mtime >= run start) ends with exactly one
          `# VERDICT: <word>` line, the word is a known verdict word, and it carries at most one
          well-formed `# JUDGED: <sha>` line.
phases:   every verifying phase of the record has a fresh verdict file named for it; a later
          cycle writes a new suffixed file (`-c2`, `-c3`) and the highest cycle decides. A
          decisive non-pass verdict is UNMET while cycles remain; after the cycle cap, or when the
          verifier itself says BLOCKED, it counts as BLOCKED - provided DONE.md records BLOCKED
          rows. A `when: changed` phase is required only when the run changed a project file;
          otherwise DONE.md carries an ARCH row (N/A with its reason).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from konstant.gate.rules.common import (Finding, Run, cycle_of, is_verdict_file, lines_of,
                                        out_files, verdict_stem, verdict_word)

JUDGED_RE = re.compile(r"^#\s*JUDGED:\s*([0-9a-f]{64})\s*$")
JUDGED_ANY = re.compile(r"^\s*#\s*JUDGED\b", re.I)
ARCH_NA_ROW = "ARCH | architecture doc matches reality | N/A | this run changed no project file"
def words(run: Run) -> dict:
    """The verdict vocabulary: recorded at gate time, else catalog/types.yaml (one source)."""
    if run.rec.get("verdict_words"):
        return run.rec["verdict_words"]
    from konstant import catalog
    return catalog.load().verdict_words()


def fresh_verdicts(run: Run) -> tuple:
    """(fresh, stale) verdict files under OUT."""
    if not run.out.is_dir():
        return [], []
    allv = [f for f in out_files(run.out) if is_verdict_file(f)]
    fresh = [f for f in allv if os.path.getmtime(f) >= run.start]
    return fresh, [f for f in allv if f not in fresh]


def decisive(run: Run) -> dict:
    """verdict file name of each verifying phase -> its decisive (highest-cycle) fresh file."""
    fresh, _ = fresh_verdicts(run)
    out = {}
    for ph in run.verifying:
        stem = verdict_stem(ph["verdict"])
        mine = [f for f in fresh if verdict_stem(f.name) == stem]
        if mine:
            out[ph["verdict"]] = max(mine, key=lambda f: (cycle_of(f.name), os.path.getmtime(f)))
    return out


def judged_line(path: Path):
    """The 64-hex sha of the file's single JUDGED line, or None."""
    try:
        found = [JUDGED_RE.match(ln.strip()) for ln in lines_of(path)]
    except OSError:
        return None
    shas = [m.group(1) for m in found if m]
    return shas[0] if len(shas) == 1 else None


def check_verdicts(run: Run) -> list:
    known = {w for ws in words(run).values() for w in ws}
    fresh, stale = fresh_verdicts(run)
    out = []
    if not fresh:
        what = (f"only STALE verdict files (older than this run): "
                f"{', '.join(f.name for f in stale)}" if stale else "no verdict file")
        return [Finding("verdicts", f"{what} under {run.out} - the verifying phases must write "
                                    "fresh verdicts", owner="producer")]
    for f in fresh:
        rel = os.path.relpath(f, run.out)
        try:
            lines = [ln.strip() for ln in lines_of(f)]
        except OSError:
            out.append(Finding("verdicts", f"{rel}: unreadable"))
            continue
        owner = f"verifier:{verdict_stem(f.name)}-verdict.md"
        vl = [ln for ln in lines if ln.startswith("# VERDICT:")]
        bad_j = [ln for ln in lines if JUDGED_ANY.match(ln) and not JUDGED_RE.match(ln)]
        good_j = [ln for ln in lines if JUDGED_RE.match(ln)]
        if not lines or not lines[-1].startswith("# VERDICT:"):
            out.append(Finding("verdicts", f"{rel} does not END with a '# VERDICT: <word>' line",
                               owner=owner))
        if len(vl) > 1:
            out.append(Finding("verdicts", f"{rel} carries {len(vl)} verdict lines - a verdict "
                                           "file is never edited; a new verdict is a new phase run",
                               owner=owner))
        word = verdict_word(f)
        if word is not None and word not in known:
            out.append(Finding("verdicts", f"{rel} ends with unknown verdict word {word!r} "
                                           f"(use {', '.join(sorted(known))})", owner=owner))
        if bad_j:
            out.append(Finding("verdicts", f"{rel} carries a malformed JUDGED line "
                                           f"{bad_j[0][:60]!r} - paste the judge command's output "
                                           "line exactly", owner=owner))
        if len(good_j) > 1:
            out.append(Finding("verdicts", f"{rel} carries {len(good_j)} '# JUDGED:' lines - "
                                           "exactly one is allowed", owner=owner))
    return out


def project_changed(run: Run) -> bool:
    from konstant.gate.rules.judged import project_state
    return bool(project_state(run.rec, since=run.start))


def done_has_blocked(run: Run) -> bool:
    p = run.out / "DONE.md"
    try:
        return any(re.search(r"\|\s*BLOCKED\s*\|", ln) for ln in lines_of(p))
    except OSError:
        return False


def check_phases(run: Run) -> list:
    out, found = [], decisive(run)
    w = words(run)
    cap = int(run.gate.get("max_cycles", 3))
    changed = None
    for ph in run.verifying:
        vf = ph["verdict"]
        if ph.get("when") == "changed":
            if changed is None:
                changed = project_changed(run)
            if not changed and vf not in found:
                out += arch_row(run)
                continue
        f = found.get(vf)
        if f is None:
            out.append(Finding("phases", f"no fresh verdict for phase {ph['agent']} "
                                         f"(expected {vf} under {run.out})",
                               owner=f"verifier:{vf}"))
            continue
        word, cycles = verdict_word(f), cycle_of(f.name)
        if word is None or word in w["pass"]:
            continue
        reason = f"{f.name} ends '# VERDICT: {word}' (phase {ph['agent']}, cycle {cycles})"
        spent = word in w["blocked"] or cycles >= cap
        if spent and done_has_blocked(run):
            out.append(Finding("phases", f"phase {ph['agent']}: {reason}", severity="blocked"))
        elif spent:
            out.append(Finding("phases", f"{reason} - record what could not be verified as a "
                                         "BLOCKED row in DONE.md (`Dn | <claim> | BLOCKED | <why>`)"))
        elif word in w["fail"]:
            out.append(Finding("phases", f"{reason} - the producer fixes it, then the verifier "
                                         f"re-runs (cycle {cycles + 1} of {cap})", owner="producer"))
        else:
            out.append(Finding("phases", f"{reason}: not a verdict word", owner=f"verifier:{vf}"))
    return out


def arch_row(run: Run) -> list:
    """Read-only types: no project change -> DONE.md carries an ARCH row instead of a verdict."""
    try:
        rows = lines_of(run.out / "DONE.md")
    except OSError:
        rows = []
    if any(re.match(r"^\|?\s*ARCH\s*\|", ln.strip(), re.I) for ln in rows):
        return []
    return [Finding("phases", f"this run changed no project file, so the architect phases did "
                              f"not run: DONE.md needs the row `{ARCH_NA_ROW}`")]


def check(run: Run) -> list:
    return check_verdicts(run) + check_phases(run)
