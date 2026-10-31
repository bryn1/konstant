"""`konstant task run`: the phase runner plus the DoD loop (DESIGN §6.5).

1. classify; small -> one harness run with the task as-is, exit = harness exit.
2. write the run record (mode runner); `--job N` is claimed when queued.
3. run every phase (runner.PhaseRunner.run_all: back-edge, cycle cap), then the close-out.
4. `task check`. UNMET -> re-run the phase that owns the FIRST reason (producer: producers +
   verifiers; verifier: that verifying phase; orchestrator: the close-out), then the close-out,
   up to [gate] max_resumes; stop early when the first reason repeats unchanged between two
   rounds (whitespace, timestamps, shas and the run paths normalised), or when no re-run can fix
   it (owner none: AUTHORSHIP). BLOCKED is never resumed.
5. MET with --job -> `job close` with evidence = the offline check command + VERIFY_EXIT=0, then
   `konstant verify` when [gate] verify_after_close.
Exit: 0 MET (and verified PASS when it ran), 3 UNMET, 4 BLOCKED, 5 check error, 2 usage,
128+n killed by signal n.
"""
from __future__ import annotations

import json
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from konstant.gate import check as check_mod
from konstant.gate import harness as harness_mod
from konstant.gate.record import konstant_cmd
from konstant.gate.runner import PhaseRunner


def normalise(reason: str, rec: dict) -> str:
    s = reason.replace(rec.get("run_dir", "\0"), "<run>").replace(rec.get("out", "\0"), "<out>")
    s = re.sub(r"\b[0-9a-f]{12,64}\b", "<sha>", s)
    s = re.sub(r"\d{4}-\d{2}-\d{2}[T ][0-9:.]+Z?", "<ts>", s)
    s = re.sub(r"\b\d{9,}\b", "<n>", s)
    return re.sub(r"\s+", " ", s).strip()


class Killed(Exception):
    def __init__(self, sig: int):
        self.sig = sig


def install_signals(started: float, err) -> None:
    def handler(signum, _frame):
        harness_mod.kill_all()
        name = signal.Signals(signum).name
        err(f"konstant task: KILLED ({name}) after {int(time.time() - started)}s - DoD UNMET")
        raise Killed(signum)
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, handler)


def dod_loop(pr: PhaseRunner, board, max_resumes: int, err) -> tuple:
    """Check, resume the owning phase, repeat. Returns (exit code, final check lines)."""
    rec, run_dir = pr.rec, pr.run_dir
    prev, resumes, rnd = None, 0, 1
    while True:
        code, lines, warns, findings = check_mod.run_check(run_dir, board)
        for w in warns:
            err(f"konstant check: {w}")
        if code != check_mod.UNMET:
            return code, lines
        first = next(f for f in findings if f.severity == "unmet")
        norm = normalise(first.line(), rec)
        if prev is not None and norm == prev:
            err(f"konstant task: STOP - first unmet reason repeated unchanged (round {rnd} == "
                f"round {rnd - 1}): {first.line()}")
            return code, lines
        if first.owner == "none":
            err(f"konstant task: STOP - no phase re-run can fix this: {first.line()}")
            return code, lines
        if resumes >= max_resumes:
            err(f"konstant task: UNMET after {resumes} resumes: {first.line()}")
            return code, lines
        prev, resumes, rnd = norm, resumes + 1, rnd + 1
        feedback = "The mechanical DoD check is UNMET:\n" + "\n".join(f"- {ln}" for ln in lines)
        err(f"konstant task: resume {resumes}/{max_resumes} ({first.owner}): {first.line()}")
        if first.owner == "producer":
            pr.rerun_producers(feedback)
        elif first.owner.startswith("verifier:"):
            pr.rerun_verifiers(only=first.owner.split(":", 1)[1])
        pr.closeout(feedback if first.owner == "orchestrator" else "")


def close_and_verify(rec: dict, client, cfg, err, out: dict | None = None) -> int:
    """MET with --job: close the job with the offline check as its evidence, then verify it.
    `out` (optional) receives the verifier's `verdict` and `reasons`."""
    job = rec["job"]
    check_cmd = konstant_cmd("task", "check", "--offline", rec["run_dir"])
    done = Path(rec["out"]) / "DONE.md"
    rows = done.read_text(errors="replace")[:2500] if done.is_file() else ""
    text = (f"VERIFY_CMD: {check_cmd}\nVERIFY_EXIT=0\nkonstant task check: MET for run "
            f"{rec['run_dir']} (type {rec['type']}, every verifying phase PASS)\n")
    if "holdouts" in rec:          # the commit the holdouts run on (docs/LEVEL5.md 3.6 step 1)
        from konstant.gate.rules.common import git_head
        head = git_head(rec.get("git_top"))
        text += (f"COMMIT={head}\n" if head else "") + \
            (f"BASE={rec['git_base']}\n" if rec.get("git_base") else "")
        rows = "".join(ln for ln in rows.splitlines(keepends=True)   # DONE.md never pins it
                       if not re.match(r"\s*(COMMIT|BASE)=", ln))
    text += rows
    ev = Path(rec["run_dir"]) / "evidence.md"
    ev.write_text(text, encoding="utf-8")
    from konstant.cli.job import parse_evidence
    res = client.post(f"/api/jobs/{job}/close", parse_evidence(str(ev)))
    err(f"konstant task: job {job} closed -> {res.get('status')}")
    if not cfg.data["gate"]["verify_after_close"]:
        return 0
    v = subprocess.run([sys.executable, "-m", "konstant", "verify", str(job), "--json"],
                       capture_output=True, text=True, env=_env(cfg), timeout=3600)
    try:
        res = json.loads(v.stdout)
    except ValueError:
        res = {}
    verdict = res.get("verdict")
    if out is not None:
        out.update(verdict=verdict, reasons=res.get("reasons") or
                   ([v.stderr.strip()[-300:]] if not verdict else []))
    err(f"konstant task: konstant verify {job} -> {verdict or v.stderr.strip()[-200:]}")
    return {"PASS": 0, "FAIL": 3, "BLOCKED": 4}.get(verdict, 5)


def _env(cfg) -> dict:
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith("KONSTANT_")}
    env["KONSTANT_HOME"] = str(cfg.home)
    return env
