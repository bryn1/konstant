"""Gate test harness: a synthetic run (record + project + OUT) the DoD rules can judge.

`Scenario.good()` builds a run that is MET; every red test plants ONE defect into it, so a red
case differs from its green twin by exactly the planted thing (two-sided calibration)."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from konstant import catalog
from konstant.config import DEFAULTS
from konstant.gate import check, record
from konstant.gate.rules import judged

SURFACES = ["backend", "db", "frontend", "api contract", "tests", "docs", "deploy"]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com",
                           "-c", "user.name=t", *args], check=True, capture_output=True, text=True)


def done_text(extra: str = "", rows=None, cleanup=True) -> str:
    lines = ["ID | claim | STATUS | evidence", "---|---|---|---",
             "D1 | greet() returns hello | PASS | pytest -q: 1 passed (test_greet.py)",
             "N1 | proof of absence | N/A | a pure function has no forbidden path"]
    lines += rows if rows is not None else \
        [f"S{i} | surface {s} | N/A | not touched by this change" for i, s in enumerate(SURFACES, 1)]
    if cleanup:
        lines.append("CLEANUP: NONE-NEEDED")
    return "\n".join(lines) + "\n" + extra


class Scenario:
    def __init__(self, tmp: Path, ttype: str = "code", use_git: bool = False,
                 mode: str = "interactive", gate: dict | None = None, job=None):
        self.cat = catalog.load()
        self.ws = tmp / "ws"
        self.project = self.ws / "projects" / "demo"
        self.project.mkdir(parents=True)
        self.git = use_git
        if use_git:
            git(self.project, "init", "-q", "-b", "main")
            (self.project / "README.md").write_text("demo\n")
            git(self.project, "add", "-A")
            git(self.project, "commit", "-qm", "init")
        self.run_dir = self.ws / "var" / "runs" / "r1"
        self.run_dir.mkdir(parents=True)
        if gate:   # task check reads [gate] from the workspace config, never from the record
            (self.ws / "konstant.toml").write_text(
                "[gate]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in gate.items()))
        self.out = self.project / ".audits" / "r1" / "out"
        gate_cfg = {**copy.deepcopy(DEFAULTS["gate"]), **(gate or {})}
        self.rec = record.build(self.cat, f"[type:{ttype}] add greet", ttype, "tag",
                                run_dir=self.run_dir, out=self.out, project=self.project,
                                workspace=self.ws, job=job, mode=mode, gate_cfg=gate_cfg,
                                start=time.time() - 5)
        record.write(self.run_dir, self.rec)
        self.ttype = ttype

    def save(self):
        record.write(self.run_dir, self.rec)

    def write(self, rel: str, text: str, where: Path | None = None) -> Path:
        p = (where or self.out) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def commit(self, *paths):
        if self.git:
            git(self.project, "add", *paths)
            git(self.project, "commit", "-qm", "work")

    def deliverable(self):
        self.write("greet.py", 'def greet():\n    return "hello"\n', self.project)
        self.commit("greet.py")
        self.write("test_greet.py", f"import sys\nsys.path.insert(0, {str(self.project)!r})\n"
                                    "from greet import greet\n\n\ndef test_greet():\n"
                                    "    assert greet() == 'hello'\n")

    def verdict(self, name: str, word: str = "PASS", judged_line: bool = True) -> Path:
        line = f"# JUDGED: {judged.judge(self.rec)}\n" if judged_line else ""
        return self.write(name, f"findings: checked\n{line}# VERDICT: {word}\n")

    def verdicts(self, word: str = "PASS"):
        for ph in self.cat.verifying(self.ttype):
            if ph.get("when") != "changed":
                self.verdict(ph["verdict"], word)

    def done(self, text: str | None = None):
        self.write("DONE.md", done_text() if text is None else text)

    def good(self):
        self.deliverable()
        self.verdicts()
        self.done()
        return self

    def manifest(self, label: str, n: int, agent: str, verdict=None, created=(), modified=(),
                 **extra):
        d = self.run_dir / "phases"
        d.mkdir(exist_ok=True)
        m = {"n": n, "agent": agent, "cycle": 1, "label": label, "verdict": verdict,
             "created": list(created), "modified": list(modified), "deleted": [], **extra}
        (d / f"{label}.json").write_text(json.dumps(m))

    def check(self, board=None, offline=False):
        code, lines, warns, findings = check.run_check(self.run_dir, board, offline)
        return code, lines, warns, findings

    def rules(self, board=None, severity=None):
        """{rule names of the findings} (optionally of one severity)."""
        return {f.rule for f in self.check(board)[3] if severity in (None, f.severity)}


def old(path: Path, seconds: int = 3600):
    t = time.time() - seconds
    os.utime(path, (t, t))


@pytest.fixture()
def scen(tmp_path):
    return lambda **kw: Scenario(tmp_path, **kw)


class FakeBoard:
    def __init__(self, jobs=None, down=False):
        self.jobs, self.down = jobs or {}, down

    def job(self, jid):
        if self.down:
            raise ConnectionError("board unreachable")
        return self.jobs.get(int(jid))
