"""`konstant task classify|gate|judge|check` and `job lint` PROBE refusals through the real CLI."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.cli.conftest import Workspace


@pytest.fixture()
def ws(tmp_path):
    w = Workspace(tmp_path)
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    return w


@pytest.mark.parametrize("task,line", [
    ("what is the board?", "small why=small-shape"),
    ("Implement a rate limiter; DoD: tests pass?", "code why=keyword:implement"),
    ("[type:docs] write the user guide", "docs why=tag"),
])
def test_classify_cli(task, line):
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "classify", task],
                         capture_output=True, text=True)
    assert res.returncode == 0 and res.stdout.strip() == line


def test_gate_prints_block_then_task_and_writes_the_record(ws, tmp_path):
    out = tmp_path / "x" / "out"
    res = ws.ok("task", "gate", "[type:code] add a CLI flag", "--out", out)
    assert res.stdout.startswith("=== TASK GATE (code) ===")
    assert res.stdout.rstrip().endswith("[type:code] add a CLI flag")
    assert len(res.stdout) <= 3300
    rec_path = res.stderr.split("run record ", 1)[1].strip()
    rec = json.loads(open(rec_path).read())
    assert rec["type"] == "code" and rec["out"] == str(out) and rec["mode"] == "interactive"
    assert [p["verdict"] for p in rec["phases"] if p["verdict"]] == \
        ["TEST-verdict.md", "REVIEW-verdict.md", "ARCH-verdict.md"]


def test_gate_small_task_prints_it_unchanged(ws):
    res = ws.ok("task", "gate", "what is the board?")
    assert res.stdout.strip() == "what is the board?"


def test_gate_project_defaults_out_under_audits(ws):
    rec = json.loads(ws.ok("task", "gate", "[type:docs] write the guide", "--project", "demo",
                           "--json").stdout)
    assert "/projects/demo/.audits/" in rec["out"] and rec["out"].endswith("/out")


def test_judge_then_check_interactive_flow(ws):
    rec = json.loads(ws.ok("task", "gate", "[type:docs] write the guide", "--project", "demo",
                           "--json").stdout)
    run_dir, out = rec["run_dir"], rec["out"]
    empty = ws.run("task", "judge", "--run", run_dir)
    assert empty.returncode == 2 and "EMPTY" in empty.stderr          # red: nothing to pin
    open(f"{out}/guide.md", "w").write("how to greet\n")
    line = ws.ok("task", "judge", "--run", run_dir).stdout.strip()
    assert line.startswith("# JUDGED: ") and len(line) == len("# JUDGED: ") + 64
    open(f"{out}/REVIEW-verdict.md", "w").write(f"accurate\n{line}\n# VERDICT: SHIP\n")
    open(f"{out}/DONE.md", "w").write("ID | claim | STATUS | evidence\nD1 | guide | PASS | "
                                      "guide.md\nCLEANUP: NONE-NEEDED\n")
    chk = ws.run("task", "check", run_dir, "--json")
    assert chk.returncode == 0, chk.stdout
    assert "AUTHORSHIP WARNING" in chk.stderr                        # interactive: unattributed
    open(f"{out}/guide.md", "a").write("edited after judging\n")
    chk = ws.run("task", "check", run_dir)
    assert chk.returncode == 3 and "changed since - out/guide.md" in chk.stdout


def test_check_usage_errors(ws, tmp_path):
    assert ws.run("task", "check", tmp_path / "nope").returncode == 2


def test_job_lint_refuses_a_probe_the_allowlist_refuses(ws):
    brief = ws.write("b.md", "x\nDoD: it works\nPROBE: cat /etc/passwd => root\n")
    res = ws.run("job", "lint", brief)
    assert res.returncode == 1 and "PROBE REFUSED" in res.stdout
    good = ws.write("g.md", "x\nDoD: it works\nPROBE: test -e projects/demo => ^ok$\n")
    assert ws.run("job", "lint", good).returncode == 0
