"""The verifier proper (DESIGN §7 steps 1-6): collect probes, re-run, settle, record.

`settle` is a pure function. `verify_job` talks to the board: it reads with whichever client it is
given and, unless dry_run, posts the verdict through POST /api/jobs/{id}/verdict.

What counts (REVIEW F-02, F-10): PASS needs at least one PROBE from the job's DoD (written by the
requester before the work) that matched. A re-run and the closer's own probes can FAIL a job, never
pass it alone: they replay the closer's claim. The re-run command is the DoD's `VERIFY_CMD:` line
when it has one; else the closer's verify_cmd, and that only in procedural mode - when this OS user
cannot read the closer-side tokens (OS-separation mode) the closer's shell is never executed by the
verifier. Every re-run runs in konstant.jail when it works (tokens and credentials masked, writes
only to the project dir). A job with sealed holdouts also runs them (verify/holdout.py: leak scan,
commitment, the pinned commit, no network) after the probes and the re-run; their findings are
redacted to ids and hints.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

from konstant.verify import holdout as holdout_mod
from konstant.verify import probe as probe_mod
from konstant.verify import rerun as rerun_mod
from konstant.verify.shapes import Roots

PENDING = "completed_unverified"


class NotVerifiable(Exception):
    """The job cannot be verified now (wrong state); the CLI exits 2."""


def collect(job: dict) -> list:
    """[(line, source)]: the acceptance's lines ("dod"), then the closer's stored ones ("closer")."""
    dod = probe_mod.probe_lines(job.get("acceptance") or "")
    closer = []
    for raw in (job.get("evidence") or {}).get("probes") or []:
        closer += probe_mod.probe_lines(str(raw))
    seen = set(dod)
    out = [(ln, "dod") for ln in dod]
    for ln in closer:
        if ln not in seen:
            seen.add(ln)
            out.append((ln, "closer"))
    return out


def settle(rows: list, rerun: dict | None, holdout: dict | None = None) -> tuple:
    """-> (PASS|FAIL|BLOCKED, reasons). Level 4: PASS = re-run ok (or none) AND >=1 DoD probe
    matched AND every probe matched; FAIL = failed re-run or any contradiction; BLOCKED = the
    rest. With holdouts (docs/LEVEL5.md 3.6 step 4) they ADD a condition and never replace one:
    a commitment mismatch or a LEAK is BLOCKED before anything else; a failed holdout or a
    LEAK-SUSPECT is FAIL; an unrunnable holdout is BLOCKED; PASS needs the level-4 PASS AND every
    sealed holdout passed - holdouts alone never pass a job (F-02)."""
    verdict, reasons = _settle4(rows, rerun)
    if holdout is None:
        return verdict, reasons
    from konstant.verify.holdout import reasons as holdout_reasons
    integrity, fail, blocked = holdout_reasons(holdout)
    if integrity:
        return "BLOCKED", integrity
    if verdict == "FAIL" or fail:
        return "FAIL", (reasons if verdict == "FAIL" else []) + fail
    if blocked:
        return "BLOCKED", (reasons if verdict == "BLOCKED" else []) + blocked
    rows_h = holdout.get("rows") or []
    if verdict != "PASS":
        return verdict, reasons
    if len(rows_h) < holdout.get("min_per_job", 1) or not all(r["passed"] for r in rows_h):
        return "BLOCKED", ["holdouts incomplete: not every sealed holdout ran and passed"]
    return "PASS", reasons + [f"{len(rows_h)} holdout(s) passed on commit "
                              f"{(holdout.get('commit') or '')[:12]}"]


def _settle4(rows: list, rerun: dict | None) -> tuple:
    kinds = [probe_mod.verdict_of(r) for r in rows]
    ran = bool(rerun) and rerun.get("ok") is not None
    reasons = []
    if rerun and rerun.get("ok") is False:
        reasons.append(rerun_failure(rerun))
    for r, k in zip(rows, kinds):
        if k == "contradiction":
            reasons.append(f"contradiction: {r['line']} -> {_show(r)}")
    if reasons:
        return "FAIL", reasons
    unverifiable = [f"unverifiable: {r['line']} -> {r['error']}"
                    for r, k in zip(rows, kinds) if k == "unverifiable"]
    if rerun and rerun.get("timed_out"):
        unverifiable.append(f"unverifiable: re-run of {rerun.get('cmd')!r} {rerun.get('skipped')}")
    if unverifiable:
        return "BLOCKED", unverifiable
    dod = sum(1 for r, k in zip(rows, kinds) if k == "matched" and r.get("source") == "dod"
              and r.get("kind", "probe") == "probe")
    if dod:
        n = kinds.count("matched") + (1 if ran else 0)
        return "PASS", [f"{n} check(s) verified: "
                        + ("re-run exit 0" if ran else "no re-run")
                        + f", {kinds.count('matched')} probe(s) matched ({dod} from the DoD)"]
    return "BLOCKED", ["nothing independent verified: no PROBE line of the job's DoD matched (a "
                       "re-run or the closer's own probes only replay the closer's claim) - add "
                       "`PROBE: <read-only command> => <regex>` to the DoD"]


def rerun_failure(rerun: dict) -> str:
    if rerun.get("commit_ok") is False:
        return f"re-run FAILED: {rerun.get('skipped')}"
    return f"re-run FAILED: {rerun.get('cmd')!r} exited {rerun.get('exit')}"


def _show(row: dict) -> str:
    return (row.get("output") or "").strip()[:200] or "(no output)"


def build_roots(cfg, projects: list) -> Roots:
    paths = [p.get("path") for p in projects]
    return Roots.build(cfg.home, cfg.section("verify"), paths)


def project_dir(cfg, projects: list, slug: str):
    for p in projects:
        if p.get("slug") == slug and p.get("path"):
            path = Path(p["path"])
            return path if path.is_absolute() else cfg.home / path
    return None


_DOD_CMD = re.compile(r"(?m)^[ \t>*-]*VERIFY_CMD:\s*(.+?)\s*$")
CLOSER_ROLES = ("orchestrator", "worker")


def separation(cfg) -> str:
    """'os-user' when this OS user cannot read a closer-side token that exists, else
    'procedural' (one user can read every token)."""
    files = [cfg.secrets_dir / f"{r}.token" for r in CLOSER_ROLES]
    if any(f.exists() and not os.access(f, os.R_OK) for f in files) or \
            (cfg.secrets_dir.exists() and not os.access(cfg.secrets_dir, os.R_OK | os.X_OK)):
        return "os-user"
    return "procedural"


def rerun_command(job: dict, mode: str) -> tuple:
    """(command, source, skipped reason): the DoD's VERIFY_CMD wins; the closer's only when
    procedural."""
    m = _DOD_CMD.search(job.get("acceptance") or "")
    if m:
        return m.group(1), "dod", None
    cmd = ((job.get("evidence") or {}).get("verify_cmd") or "").strip()
    if not cmd:
        return None, None, "the evidence has no verify_cmd"
    if mode == "os-user":
        return None, "closer", ("OS-separation mode: the verifier never executes the closer's "
                                "verify_cmd; put `VERIFY_CMD: <cmd>` in the DoD to have it re-run")
    return cmd, "closer", None


def verify_job(client, cfg, ref, *, dry_run: bool, rerun: bool = True, projects=None) -> dict:
    """Run steps 1-6 for one job; returns the result dict. Raises NotVerifiable on wrong state."""
    started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    job = client.get(f"/api/jobs/{ref}")
    if job["status"] != PENDING:
        raise NotVerifiable(f"job {job['display_id']} is {job['status']}, not {PENDING}: "
                            "only a closed, unverified job can be verified")
    if projects is None:
        projects = client.get("/api/projects")["projects"]
    vcfg = cfg.section("verify")
    roots = build_roots(cfg, projects)
    rows = [probe_mod.run_line(ln, roots, src, vcfg["probe_timeout_s"])
            for ln, src in collect(job)]
    res = None
    if rerun and vcfg["rerun"]:
        cmd, source, skipped = rerun_command(job, separation(cfg))
        if cmd is None:
            res = rerun_mod.skipped(skipped, source)
        else:
            res = rerun_mod.rerun({**(job.get("evidence") or {}), "verify_cmd": cmd},
                                  project_dir(cfg, projects, job["project"]),
                                  vcfg["rerun_timeout_s"], source=source, home=cfg.home,
                                  jail=cfg.data["gate"]["jail"])
    hres = holdout_mod.evaluate(client, cfg, job, projects)
    verdict, reasons = settle(rows, res, hres)
    hpub = holdout_mod.public(hres)
    out = {"job": job["id"], "display_id": job["display_id"], "verdict": verdict,
           "reasons": reasons, "probes": rows, "rerun": res, "dry_run": dry_run}
    if hpub is not None:
        out["holdouts"] = hpub
    if not dry_run:
        findings = [r for r in reasons if verdict == "FAIL"]
        client.post(f"/api/jobs/{job['id']}/verdict", {
            "verdict": verdict, "reason": "; ".join(reasons), "findings": findings,
            "probes": rows, "rerun": res, "started_at": started,
            **({"holdout": hpub} if hpub is not None else {})})
    return out
