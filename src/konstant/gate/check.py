"""`konstant task check <run>`: the mechanical DoD check (DESIGN §6.4). Deterministic, no model.

Exit 0 MET (stdout empty) · 3 UNMET (one reason per line) · 4 BLOCKED (nothing unmet, but DONE.md
or a verifier honestly reports what could not be verified; lines start `BLOCKED: `; never resumed,
never MET) · 5 the check itself failed (never MET) · 2 usage.
Rule order is fixed (the loop's repeat-stop compares the FIRST reason): verdicts, phases,
authorship, judged, done, absence, surfaces, cleanup, tests, exercise, lastmile, hygiene,
holdouts, verified. The DECLINED filter runs last; it never excuses a finding of the rules in
UNEXCUSABLE (authorship, verdicts, phases, judged, tests, verified, holdouts: what the verifying
phases, the tests and the holdouts say is never waived by text the close-out agent writes;
REVIEW F-01, docs/LEVEL5.md 3.6 step 7).

What is trusted: only run dirs directly under `<workspace>/var/runs/` are judged (the workspace
is KONSTANT_HOME / --config when the caller has one, else the one the run dir sits in); the
record supplies only run facts (task, type, OUT, project, base, start, job, mode); the phases,
verdict words, DONE.md shape and the [gate] settings (test_cmd above all) are re-derived from the
workspace's catalog and konstant.toml, never read from the record (REVIEW F-06, F-11).
"""
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

from konstant import catalog, config
from konstant.gate import record
from konstant.gate.rules import (authorship, cleanup, done, holdouts, hygiene, judged, lastmile,
                                 tests, verdicts, verified)
from konstant.gate.rules.common import Finding, Run

MET, UNMET, BLOCKED, CHECK_ERROR, USAGE = 0, 3, 4, 5, 2
RULES = (("verdicts", verdicts.check_verdicts), ("phases", verdicts.check_phases),
         ("authorship", authorship.check), ("judged", judged.check), ("done", done.check),
         ("cleanup", cleanup.check), ("tests", tests.check), ("lastmile", lastmile.check),
         ("hygiene", hygiene.check), ("holdouts", holdouts.check), ("verified", verified.check))
UNEXCUSABLE = {"authorship", "verdicts", "phases", "judged", "tests", "verified", "holdouts"}


class CheckUsage(Exception):
    pass


class BoardView:
    """The two board reads a check needs (job + its verifications), through the CLI client."""

    def __init__(self, client):
        self.client = client

    def job(self, job_id):
        from konstant.client import ClientError
        try:
            return self.client.get(f"/api/jobs/{job_id}", trail=True)
        except ClientError as exc:
            if exc.status == 404:
                return None
            raise


def workspace_of(run_dir: Path, home=None) -> Path:
    """The workspace that owns `run_dir`; CheckUsage unless run_dir is <workspace>/var/runs/<x>."""
    rd = Path(os.path.realpath(run_dir))
    if home is not None:
        ws = Path(os.path.realpath(home))
        if rd.parent != ws / "var" / "runs":
            raise CheckUsage(f"{rd} is not a run dir under {ws / 'var' / 'runs'}: task check "
                             "judges only run records konstant wrote under var/runs/")
        return ws
    if rd.parent.name != "runs" or rd.parent.parent.name != "var":
        raise CheckUsage(f"{rd} is not a run dir under <workspace>/var/runs/: task check judges "
                         "only run records konstant wrote there")
    return rd.parent.parent.parent


def load_run(path, board=None, offline: bool = False, home=None) -> Run:
    p = Path(path)
    rec_path = p / "record.json" if p.is_dir() else p
    try:
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CheckUsage(f"no run record at {rec_path} (a run dir holds record.json)")
    except (OSError, ValueError) as exc:
        raise CheckUsage(f"{rec_path}: unreadable run record ({exc})")
    if not isinstance(rec, dict) or not rec.get("out") or not rec.get("type"):
        raise CheckUsage(f"{rec_path}: not a konstant run record (needs out and type)")
    ws = workspace_of(rec_path.parent, home)
    try:
        cfg = config.load(ws)
        cat = catalog.load(catalog.find_root(ws, cfg.data["catalog"]["path"]))
    except (config.ConfigError, catalog.CatalogError) as exc:
        raise CheckUsage(f"workspace {ws}: {exc}")
    if rec["type"] not in cat.types:
        raise CheckUsage(f"{rec_path}: unknown type {rec['type']!r} in this workspace's catalog")
    if rec.get("mode") not in ("runner", "interactive"):
        raise CheckUsage(f"{rec_path}: mode must be runner or interactive")
    rec = {**rec, **record.catalog_fields(cat, rec["type"], cfg.data["gate"])}
    return Run(run_dir=rec_path.parent, rec=rec, catalog=cat, board=None if offline else board,
               offline=offline, workspace=ws)


def evaluate(run: Run) -> list:
    run.out.mkdir(parents=True, exist_ok=True)   # an absent OUT is UNMET by the rules, not a skip
    findings = []
    for _name, rule in RULES:
        findings += rule(run)
    excusable = [f for f in findings if f.rule not in UNEXCUSABLE]
    kept, _n = done.apply_declined(run, excusable)
    return [f for f in findings if f.rule in UNEXCUSABLE] + kept


def decide(findings: list) -> tuple:
    """(exit code, stdout lines, stderr warnings)."""
    warns = [f.text for f in findings if f.severity == "warn"]
    unmet = [f for f in findings if f.severity == "unmet"]
    blocked = [f for f in findings if f.severity == "blocked"]
    if unmet:
        return UNMET, [f.line() for f in unmet], warns
    if blocked:
        return BLOCKED, [f.line() for f in blocked], warns
    return MET, [], warns


def run_check(path, board=None, offline: bool = False, home=None) -> tuple:
    """(exit code, stdout lines, stderr lines, findings). Never raises for a rule failure."""
    try:
        run = load_run(path, board, offline, home)
    except CheckUsage as exc:
        return USAGE, [], [str(exc)], []
    try:
        findings = evaluate(run)
    except Exception as exc:  # a crashed check is never MET
        tb = traceback.format_exc(limit=3).strip().splitlines()[-1]
        return CHECK_ERROR, [f"CHECK-ERROR: the DoD could not be checked: {exc!r}"], [tb], []
    code, lines, warns = decide(findings)
    return code, lines, warns, findings


def as_json(code: int, findings: list) -> dict:
    return {"exit": code, "result": {MET: "MET", UNMET: "UNMET", BLOCKED: "BLOCKED"}.get(code, "ERROR"),
            "findings": [{"rule": f.rule, "owner": f.owner, "severity": f.severity, "text": f.text}
                         for f in findings]}


__all__ = ["Finding", "run_check", "load_run", "evaluate", "decide", "BoardView", "as_json"]
