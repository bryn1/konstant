"""The job lifecycle end to end through the CLI against a real board."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from konstant.cli.job import parse_evidence
from tests.cli.conftest import REPO

BRIEF = "Say hello.\n\nDoD: greet() returns hello (pytest tests/test_greet.py exits 0)\n"
GOOD = "VERIFY_CMD: pytest -q\n12 passed in 0.31s\nVERIFY_EXIT=0\nDOCS: n/a - test\n"


def _add(ws, title="T1: hello", brief=BRIEF, *extra) -> str:
    out = ws.ok("job", "add", title, "--project", "demo", "--type", "code",
                "--brief", ws.write("brief.md", brief), *extra).stdout
    return out.split()[0].split("=")[1]


def _claimed(ws) -> str:
    job = _add(ws)
    ws.ok("job", "claim", job)
    return job


def test_lifecycle_to_completed_unverified_then_verified(ws):
    job = _claimed(ws)
    ws.ok("job", "close", job, "--evidence", ws.write("ev.md", GOOD))
    shown = ws.ok("job", "show", job, "--json").stdout
    assert '"status": "completed_unverified"' in shown
    assert json.loads(shown)["evidence"]["verify_cmd"] == "pytest -q"
    ws.ok("--as", "verifier", "job", "verdict", job, "PASS")
    assert json.loads(ws.ok("job", "show", job, "--json").stdout)["status"] == "verified"


@pytest.mark.parametrize("evidence,needle", [
    ("VERIFY_CMD: pytest -q\n12 passed\n", "VERIFY_EXIT=0"),
    ("VERIFY_CMD: pytest -q\nRan 0 tests in 0.000s\n\nOK\nVERIFY_EXIT=0\n", "vacuous"),
    ("VERIFY_CMD: pytest -q\n1 failed, 3 passed\nVERIFY_EXIT=1\n", "verify_exit is 1"),
    ("VERIFY_CMD: pytest -q\n3 passed\nVERIFY_EXIT=0\nVERIFY_EXIT=2\n", "verify_exit is 2"),
    ("12 passed\nVERIFY_EXIT=0\n", "verify_cmd is missing"),
])
def test_close_refusals_exit_1_and_name_the_problem(ws, evidence, needle):
    job = _claimed(ws)
    res = ws.run("job", "close", job, "--evidence", ws.write("bad.md", evidence))
    assert res.returncode == 1 and needle in res.stderr, res.stderr
    assert json.loads(ws.ok("job", "show", job, "--json").stdout)["status"] == "claimed"


def _wrapper_or_python(ws):
    venv_python = REPO / ".venv" / "bin" / "python"
    if venv_python.exists():
        return [str(REPO / "bin" / "konstant")]
    return [sys.executable, "-m", "konstant"]


def test_orchestrator_verdict_is_403_naming_the_verify_roles(ws):
    job = _claimed(ws)
    ws.ok("job", "close", job, "--evidence", ws.write("ev.md", GOOD))
    res = subprocess.run(_wrapper_or_python(ws) + ["--as", "orchestrator", "job", "verdict",
                                                   job, "PASS"],
                         capture_output=True, text=True, env=ws.env(), timeout=60)
    assert res.returncode == 1
    assert "HTTP 403" in res.stderr and "verifier, owner" in res.stderr


def test_closer_cannot_verify_from_the_cli(ws):
    job = _add(ws)
    ws.ok("job", "claim", job)
    ws.ok("--as", "owner", "job", "close", job, "--evidence", ws.write("ev.md", GOOD))
    res = ws.run("--as", "owner", "job", "verdict", job, "PASS")
    assert res.returncode == 1 and "403" in res.stderr and "the closer cannot verify" in res.stderr


def test_add_without_dod_and_too_deep(ws):
    res = ws.run("job", "add", "T: no dod", "--project", "demo", "--type", "code",
                 "--brief", ws.write("nodod.md", "Make it good.\n"))
    assert res.returncode == 1 and "acceptance is required" in res.stderr
    feature = _add(ws, "T: feature")
    task = _add(ws, "T: task", BRIEF, "--parent", feature)
    res = ws.run("job", "add", "T: deep", "--project", "demo", "--type", "code",
                 "--brief", ws.write("b.md", BRIEF), "--parent", task)
    assert res.returncode == 1 and "depth > 2" in res.stderr


def test_add_reads_brief_from_stdin_and_warns_on_lint(ws):
    res = ws.run("job", "add", "T: stdin", "--project", "demo", "--type", "infra", "--brief", "-",
                 stdin="Ship it.\nDoD: the service is deployed\n")
    assert res.returncode == 0 and "konstant WARN: DoD LIVE" in res.stderr


def test_not_found_and_usage_exit_2(ws):
    res = ws.run("job", "show", "4040")
    assert res.returncode == 2 and "not found" in res.stderr
    assert ws.run("job", "frobnicate").returncode == 2
    assert ws.run("job", "add", "T: x", "--project", "nope", "--type", "code", "--brief",
                  ws.write("b.md", BRIEF)).returncode == 2


def test_in_task_runs_cannot_act_as_verifier_or_owner(ws):
    env = ws.env(KONSTANT_IN_TASK="1")
    for role in ("verifier", "owner"):
        res = ws.run("--as", role, "job", "list", env=env)
        assert res.returncode == 1 and "KONSTANT_IN_TASK" in res.stderr
    assert ws.run("--as", "worker", "job", "list", env=env).returncode == 0


def test_note_block_reopen_cancel_move_list_search(ws):
    feature = _add(ws, "T: parent feature")
    job = _claimed(ws)
    ws.ok("job", "note", job, "looked", "at", "it")
    ws.ok("job", "note", job, "bug in greet", "--kind", "finding")
    ws.ok("job", "block", job, "waiting", "for", "input")
    ws.ok("--as", "owner", "job", "reopen", job, "input", "arrived")
    moved = ws.ok("--as", "owner", "job", "move", job, "--parent", feature, "--reason", "x").stdout
    assert "display=" in moved
    ws.ok("--as", "owner", "job", "cancel", job, "superseded")
    trail = json.loads(ws.ok("job", "show", job, "--trail", "--json").stdout)["trail"]
    assert [t["kind"] for t in trail] == ["status", "status", "note", "finding", "status",
                                          "status", "move", "status"]
    tree = ws.ok("job", "list", "--tree").stdout
    assert "[project:demo]" in tree and "  " in tree
    assert "parent feature" in ws.ok("job", "search", "parent", "--open").stdout


def test_review_job(ws):
    out = ws.ok("job", "add", "T: write guide", "--project", "demo", "--type", "docs",
                "--brief", ws.write("b.md", BRIEF)).stdout
    job = out.split()[0].split("=")[1]
    ws.ok("job", "claim", job)
    verdict, done = ws.write("v.md", "ok\n# VERDICT: SHIP\n"), ws.write("d.md", "| R1 | x | PASS |")
    res = ws.run("--as", "worker", "job", "review", job, "--verdict", verdict, "--done", done)
    assert res.returncode == 1 and "requires role owner, orchestrator, verifier" in res.stderr
    own = ws.run("job", "review", job, "--verdict", verdict, "--done", done)   # filed + claimed it
    assert own.returncode == 1 and "another identity" in own.stderr
    ws.ok("--as", "owner", "job", "review", job, "--verdict", verdict, "--done", done)
    assert json.loads(ws.ok("job", "show", job, "--json").stdout)["status"] == "reviewed"


def test_approval_flow(ws):
    job = _add(ws, "T: risky", BRIEF, "--approval")
    assert "waiting_approval" in ws.ok("job", "show", job).stdout
    assert ws.run("job", "approve", job).returncode == 1
    ws.ok("--as", "owner", "job", "approve", job)


def test_lint_command(ws):
    assert ws.run("job", "lint", ws.write("l.md", "No dod here")).returncode == 1
    res = ws.ok("job", "lint", ws.write("l.md", "DoD: page looks right"))
    assert "VISUAL" in res.stdout


def test_parse_evidence(tmp_path):
    f = tmp_path / "ev.md"
    f.write_text("VERIFY_CMD= make test\nout\nVERIFY_EXIT=0\nCONTROL_CMD: make bad\n"
                 "CONTROL_EXIT=2\nCOMMIT=abc123\nBASE=def456\nPROBE: test -e x => ^ok$\n"
                 "DOCS: README.md\n")
    p = parse_evidence(str(f))
    assert p["verify_cmd"] == "make test" and p["verify_exit"] == 0
    assert (p["control_cmd"], p["control_exit"]) == ("make bad", 2)
    assert (p["commit"], p["base"], p["docs"]) == ("abc123", "def456", "README.md")
    assert p["probes"] == ["PROBE: test -e x => ^ok$"]
    assert p["evidence_path"] == str(Path(f).resolve())
    f.write_text("x" * 9000)
    assert len(parse_evidence(str(f))["verify_output"]) == 4000
    assert "verify_exit" not in parse_evidence(str(f))
