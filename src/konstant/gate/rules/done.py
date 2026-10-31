"""Rules `done`, `absence`, `surfaces` and the DECLINED marker (DESIGN §6.4).

done:     DONE.md under OUT, fresh, rows `ID | claim | STATUS | evidence`, STATUS in PASS FAIL
          BLOCKED N/A UNVERIFIED. Every line that looks like a row counts. FAIL, UNVERIFIED, an
          unknown or misplaced status, a missing evidence cell, a PASS whose evidence is a
          placeholder (-, ok, done, yes, pass ...), N/A or BLOCKED without a reason, zero rows or no
          PASS row = UNMET. BLOCKED rows make the run BLOCKED (exit 4) when nothing else is unmet.
          The header is the line whose first four cells are exactly ID | claim | STATUS |
          evidence; every other line is a row (a `status` word in a cell hides nothing; F-09).
dod:      a run bound to a job (`--job`): one `DoD-<n>` row per row of the job's DoD (numbered
          by board.dod.dod_rows, handed to the close-out as KONSTANT-DOD-ROW lines), PASS or
          BLOCKED - never N/A, never missing (REVIEW F-21).
absence:  build types: >= 1 `N<n>` proof-of-absence row (or `N1 | proof of absence | N/A | why`).
surfaces: build types: one `surface <name>` row per surface in the catalog, PASS or N/A + reason.
DECLINED: `DECLINED | <claim> | job <id>` excuses an EXCUSABLE unmet/blocked condition only when
          BOTH hold: the claim QUOTES the condition (>= 2 contiguous shared words, claim >= 3
          words) AND job <id> on the board carries an OWNER-role note or approval reading
          `DECLINED: <the same claim>` - something the close-out agent cannot author (REVIEW
          F-01). Free text, a quoted "owner statement" and "any existing job" resolve nothing; an
          offline check or an unreachable board resolves nothing (fail closed). A malformed or
          unresolvable marker is itself UNMET. Findings of check.UNEXCUSABLE rules are never
          excused.
"""
from __future__ import annotations

import os
import re

from konstant.gate.rules.common import Finding, Run

STATUSES = ("PASS", "FAIL", "BLOCKED", "N/A", "UNVERIFIED")
PLACEHOLDER = {"", "-", "--", "ok", "okay", "done", "yes", "y", "pass", "passed", "true",
               "verified", "works", "fine", "n/a", "na", "none", "tbd", "x", "see above"}
SURFACE_ALIASES = {"back-end": "backend", "database": "db", "schema": "db", "front-end": "frontend",
                   "ui": "frontend", "api": "api contract", "contract": "api contract",
                   "api-contract": "api contract", "test": "tests", "doc": "docs",
                   "documentation": "docs", "deployment": "deploy"}
NEGATIVE_ID = re.compile(r"^N\d+$", re.I)
SURFACE_CLAIM = re.compile(r"^surface\s*[:\-]?\s*(.+?)\s*$", re.I)
MARKER = "DECLINED | <claim> | job <id>"
CLAIM_MIN_WORDS = 3
JOB_REF = re.compile(r"\bjob\s*#?\s*(\d+)\b", re.I)
HEADER = ["ID", "CLAIM", "STATUS", "EVIDENCE"]
DOD_ID = re.compile(r"^DoD-(\d+)$", re.I)


def cells(line: str) -> list:
    body = line[1:] if line.startswith("|") else line
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def placeholder(ev: str) -> bool:
    e = ev.strip().strip("*`_ .").lower()
    return e in PLACEHOLDER or not re.search(r"[a-z0-9]", e)


def read_rows(run: Run):
    """(findings, rows) with rows = [(id, claim, status, evidence)]."""
    path = run.out / "DONE.md"
    if not path.is_file():
        return [Finding("done", f"DONE.md missing under {run.out} (rows: ID | claim | "
                                "PASS|FAIL|BLOCKED|N/A|UNVERIFIED | evidence)")], []
    if os.path.getmtime(path) < run.start:
        return [Finding("done", f"DONE.md under {run.out} is STALE (older than this run)")], []
    out, rows = [], []
    for n, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if "|" not in line or line.startswith("#"):
            continue
        cs = cells(line)
        if len(cs) < 2 or all(re.fullmatch(r":?-{2,}:?", c) for c in cs if c):
            continue
        norm = [c.strip("*`_ ").upper() for c in cs]
        if norm[:4] == HEADER or norm[0] == "DECLINED":
            continue
        at = [i for i, c in enumerate(norm) if c in STATUSES]
        if len(cs) < 3 or norm[2] not in STATUSES:
            if at and at[0] > 2:
                out.append(Finding("done", f"DONE.md line {n}: status '{cs[at[0]]}' is in cell "
                                           f"{at[0] + 1}, not the 3rd - an unescaped | in an "
                                           f"earlier cell split the row; escape it as \\|"))
            elif at:
                out.append(Finding("done", f"DONE.md line {n}: status '{cs[at[0]]}' is in cell "
                                           f"{at[0] + 1}, not the 3rd: `ID | claim | STATUS | "
                                           "evidence`"))
            elif len(cs) >= 3:
                out.append(Finding("done", f"DONE.md line {n}: unknown status '{cs[2]}' (use "
                                           f"{'|'.join(STATUSES)})"))
            continue
        status, rid, claim = norm[2], cs[0], cs[1]
        ev = " | ".join(cs[3:]).strip()
        rows.append((rid, claim, status, ev))
        short = claim[:80]
        if status in ("FAIL", "UNVERIFIED"):
            out.append(Finding("done", f"DONE.md {rid} is {status}: {short}"))
        elif len(cs) < 4 or not ev:
            out.append(Finding("done", f"DONE.md {rid} is {status} with no evidence cell: {short}"))
        elif status == "PASS" and placeholder(ev):
            out.append(Finding("done", f"DONE.md {rid} is PASS with placeholder evidence "
                                       f"'{ev[:20]}' - name the proof (command + output, a path, "
                                       f"a sha): {short}"))
        elif status in ("N/A", "BLOCKED") and placeholder(ev):
            out.append(Finding("done", f"DONE.md {rid} is {status} with no reason: {short}"))
        elif status == "BLOCKED":
            out.append(Finding("done", f"{rid} | {short} | {ev[:160]}", severity="blocked"))
    if not rows:
        out.append(Finding("done", "DONE.md has no matrix rows (ID | claim | STATUS | evidence)"))
    elif not any(r[2] in ("PASS", "BLOCKED") for r in rows):
        out.append(Finding("done", "DONE.md has no PASS row - nothing is claimed done"))
    return out, rows


def surface_name(claim: str):
    m = SURFACE_CLAIM.match(claim.strip("*`_ "))
    if not m:
        return None
    name = re.sub(r"\s+", " ", m.group(1).strip("*`_ .").lower())
    return SURFACE_ALIASES.get(name, name)


def check_dod(run: Run, rows: list) -> list:
    """With a job: every DoD row has its `DoD-<n>` DONE row, PASS or BLOCKED."""
    if not run.rec.get("job") or not run.rec.get("acceptance"):
        return []
    from konstant.board.dod import dod_rows
    want = dod_rows(run.rec["acceptance"])
    have = {}
    for r in rows:
        m = DOD_ID.match(r[0].strip("*`_ "))
        if m:
            have[int(m.group(1))] = r
    out = []
    for i, text in enumerate(want, 1):
        r = have.get(i)
        if r is None:
            out.append(Finding("done", f"DONE.md has no row DoD-{i} for the job's DoD row "
                                       f"'{text[:80]}' (`DoD-{i} | <claim> | PASS | <evidence>`)"))
        elif r[2] == "N/A":
            out.append(Finding("done", f"DONE.md DoD-{i} is N/A: a row of the job's DoD is "
                                       "delivered (PASS) or honestly BLOCKED, never N/A"))
    return out


def check_rows(run: Run, rows: list) -> list:
    want = run.rec.get("done_rows") or {}
    if not rows or not want:
        return []
    out, t = [], run.rec.get("type")
    if want.get("negative") and not any(NEGATIVE_ID.match(r[0].strip("*`_ ")) for r in rows):
        out.append(Finding("absence", f"DONE.md has no proof-of-absence row ([type:{t}]): add "
                                      "`N1 | <forbidden behaviour> is impossible | PASS | <the "
                                      "check and its output>` or `N1 | proof of absence | N/A | "
                                      "<reason>`"))
    need = [str(x).lower() for x in want.get("surfaces") or []]
    have = {surface_name(r[1]) for r in rows}
    missing = [n for n in need if n not in have]
    if missing:
        out.append(Finding("surfaces", f"DONE.md lacks surface row(s) {', '.join(missing)} "
                                       f"([type:{t}]): `S<n> | surface <name> | PASS | <evidence>` "
                                       "or `... | N/A | <why this change does not touch it>`"))
    return out


def check(run: Run) -> list:
    found, rows = read_rows(run)
    return found + (check_dod(run, rows) if rows else []) + check_rows(run, rows)


# --- DECLINED ------------------------------------------------------------------------------
def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def ref_resolves(ref: str, claim: str, board) -> bool:
    """True when a referenced job carries an owner-role note/approval `DECLINED: <claim>`."""
    ids = [int(x) for x in JOB_REF.findall(ref)]
    if not ids or board is None:
        return False
    want = _words(claim)
    for jid in ids:
        try:
            job = board.job(jid)
        except Exception:      # unreachable board: cannot confirm -> does not resolve
            return False
        for t in (job or {}).get("trail") or []:
            body = str(t.get("body") or "")
            if (t.get("role") == "owner" and t.get("kind") in ("note", "approval")
                    and body.strip().upper().startswith("DECLINED:")
                    and _words(body.split(":", 1)[1]) == want):
                return True
    return False


def declined(run: Run) -> tuple:
    """(claims, marker findings) of the DECLINED rows in DONE.md (read whatever its mtime)."""
    claims, out = [], []
    try:
        text = (run.out / "DONE.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return claims, out
    for raw in text.splitlines():
        line = raw.strip()
        if "|" not in line or line.startswith("#"):
            continue
        cs = cells(line)
        if not cs or cs[0].strip("*`_ ").upper() != "DECLINED":
            continue
        claim = cs[1].strip() if len(cs) > 1 else ""
        ref = " | ".join(cs[2:]).strip()
        if not claim:
            out.append(Finding("done", f"DONE.md DECLINED row has no claim: `{MARKER}`"))
        elif len(cs) < 3 or placeholder(ref):
            out.append(Finding("done", f"DONE.md DECLINED row '{claim[:60]}' cites no ruling: "
                                       f"`{MARKER}`"))
        elif len(re.findall(r"[a-z0-9]+", claim.lower())) < CLAIM_MIN_WORDS:
            out.append(Finding("done", f"DONE.md DECLINED row '{claim[:60]}' is a word-list, not a "
                                       f"claim - quote the condition it closes: `{MARKER}`"))
        elif not ref_resolves(ref, claim, run.board):
            out.append(Finding("done", f"DONE.md DECLINED row '{claim[:60]}' is not an owner "
                                       "decision: it must cite `job <id>` whose trail carries an "
                                       f"owner note `DECLINED: {claim[:60]}` (`konstant --as owner "
                                       "job note <id> ...`), read from a reachable board"))
        else:
            claims.append(claim)
    return claims, out


def covers(claim: str, text: str) -> bool:
    cw = re.findall(r"[a-z0-9]+", claim.lower())
    tw = re.findall(r"[a-z0-9]+", text.lower())
    if len(cw) < 2 or len(tw) < 2:
        return False
    return bool({(cw[i], cw[i + 1]) for i in range(len(cw) - 1)}
                & {(tw[i], tw[i + 1]) for i in range(len(tw) - 1)})


def apply_declined(run: Run, findings: list) -> tuple:
    """(kept findings, number excused). Marker findings are added and cannot be excused."""
    claims, markers = declined(run)
    if not claims:
        return findings + markers, 0
    kept = [f for f in findings
            if f.severity == "warn" or not any(covers(c, f.text) for c in claims)]
    return kept + markers, len(findings) - len(kept)
