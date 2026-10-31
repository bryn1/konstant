"""`konstant task run` end to end with the deterministic fake harness plus the
signal stop, the small path and the --job close + verify path."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.cli.conftest import Workspace, free_port

REPO = Path(__file__).resolve().parents[2]
FAKE = f"{sys.executable} {REPO / 'tests' / 'fixtures' / 'fake_harness.py'} {{prompt_file}}"


@pytest.fixture()
def ws(tmp_path):
    """A workspace with projects/demo and NO board: the runner falls back to projects/<slug>."""
    w = Workspace(tmp_path)
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    return w


def run(w, mode="", *extra, task="[type:code] add greet()"):
    env = w.env(**({"FAKE_HARNESS_MODE": mode} if mode else {}))
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run", task, "--project",
                          "demo", "--harness", FAKE, *extra], capture_output=True, text=True,
                         env=env, timeout=300, cwd=str(w.home))
    runs = sorted((w.home / "var" / "runs").iterdir())
    return res, runs[-1]


def out_of(run_dir: Path) -> Path:
    return Path(json.loads((run_dir / "record.json").read_text())["out"])


def test_run_met(ws):
    res, rd = run(ws)
    assert res.returncode == 0, res.stderr
    assert ws.run("task", "check", rd).returncode == 0
    manifests = sorted((rd / "phases").glob("*.json"))
    assert [json.loads(m.read_text())["agent"] for m in manifests] == \
        ["architect", "coder", "tester", "reviewer", "architect", "orchestrator"]
    assert (ws.home / "projects" / "demo" / "greet.py").is_file()


def test_run_producer_writes_verdict_is_authorship(ws):
    res, rd = run(ws, "producer-writes-verdict")
    assert res.returncode == 3
    chk = ws.run("task", "check", rd)
    assert chk.returncode == 3
    assert any(ln.startswith("AUTHORSHIP:") for ln in chk.stdout.splitlines())


def test_run_tester_fails_3x_is_blocked(ws):
    res, rd = run(ws, "tester-fails-3x")
    assert res.returncode == 4, res.stderr
    rows = [ln for ln in (out_of(rd) / "CYCLES.md").read_text().splitlines() if ln[:1].isdigit()]
    assert len(rows) == 3
    assert (out_of(rd) / "TEST-verdict-c3.md").is_file()
    assert not (out_of(rd) / "TEST-verdict-c4.md").exists()


def test_run_same_unmet_stops_on_the_repeat(ws):
    res, rd = run(ws, "same-unmet")
    assert res.returncode == 3
    assert "first unmet reason repeated unchanged (round 2 == round 1)" in res.stderr
    assert res.stderr.count("resume 1/") == 1 and "resume 2/" not in res.stderr


def test_run_in_a_git_project_commits_and_is_met(ws):
    proj = ws.home / "projects" / "demo"
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-C", str(proj), "-c", "user.email=t@example.com", "-c",
                        "user.name=t", *args], check=True)
    res, rd = run(ws)
    assert res.returncode == 0, res.stdout + res.stderr


def test_run_small_task_is_one_harness_run(ws):
    res, rd = run(ws, task="what is the board?")
    assert res.returncode == 0 and "small (small-shape)" in res.stderr
    assert not (rd / "record.json").exists() and (rd / "phases" / "small.log").is_file()


def test_run_sigterm_stops_the_harness(ws, tmp_path):
    marker = tmp_path / "child.pid"
    slow = (f"{sys.executable} -c \"import os,time; open('{marker}','w').write(str(os.getpid()));"
            f" time.sleep(60)\" {{prompt_file}}")
    p = subprocess.Popen([sys.executable, "-m", "konstant", "task", "run", "[type:code] add x",
                          "--project", "demo", "--harness", slow], env=ws.env(),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         cwd=str(ws.home))
    deadline = time.time() + 30
    while not marker.exists() and time.time() < deadline:
        time.sleep(0.1)
    time.sleep(0.3)
    p.send_signal(signal.SIGTERM)
    _out, err = p.communicate(timeout=30)
    assert p.returncode == 128 + signal.SIGTERM
    assert "KILLED (SIGTERM)" in err and "DoD UNMET" in err
    child = int(marker.read_text())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def test_run_bad_harness_template_is_usage(ws):
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run", "[type:code] x",
                          "--project", "demo", "--harness", "tool --no-prompt"],
                         capture_output=True, text=True, env=ws.env(), cwd=str(ws.home))
    assert res.returncode == 2 and "needs {prompt}" in res.stderr


def test_run_with_a_job_closes_and_verifies(tmp_path):
    w = Workspace(tmp_path)
    w.ok("board", "init")
    w.ok("board", "start")
    try:
        w.ok("project", "add", "demo")
        brief = w.write("brief.md", "add greet\nDoD: greet exists\n"
                                    "PROBE: test -e projects/demo/greet.py => ^ok$\n")
        job = json.loads(w.ok("job", "add", "add greet", "--project", "demo", "--type", "code",
                              "--brief", brief, "--json").stdout)["id"]
        res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                              "[type:code] add greet()", "--job", str(job), "--harness", FAKE],
                             capture_output=True, text=True, env=w.env(), timeout=300,
                             cwd=str(w.home))
        assert res.returncode == 0, res.stderr
        shown = json.loads(w.ok("job", "show", str(job), "--json").stdout)
        assert shown["status"] == "verified", res.stderr
        assert [v["verdict"] for v in shown["verifications"]] == ["PASS"]
        assert [r["result"] for r in shown["runs"]] == ["MET"]
        rd = sorted((w.home / "var" / "runs").iterdir())[-1]
        assert w.run("task", "check", rd).returncode == 0       # verified rule reads the board
        # red twin: the same run bound to a closed job with no verdict is UNMET by rule verified
        job2 = json.loads(w.ok("job", "add", "second", "--project", "demo", "--type", "code",
                               "--brief", brief, "--json").stdout)["id"]
        w.ok("job", "claim", str(job2))
        w.ok("job", "close", str(job2), "--evidence", str(rd / "evidence.md"))
        rec = json.loads((rd / "record.json").read_text())
        rec["job"] = job2
        (rd / "record.json").write_text(json.dumps(rec))
        chk = w.run("task", "check", rd)
        assert chk.returncode == 3 and "has no konstant verify verdict" in chk.stdout
    finally:
        w.run("board", "stop")


def test_gate_with_an_unknown_job_is_exit_2(tmp_path):
    w = Workspace(tmp_path)
    w.ok("board", "init")
    w.ok("board", "start")
    try:
        w.ok("project", "add", "demo")
        res = w.run("task", "gate", "[type:code] add greet", "--job", "999")
        assert res.returncode == 2 and "not found" in res.stderr
    finally:
        w.run("board", "stop")


def test_free_port_helper_is_loopback():
    assert 0 < free_port() < 65536
