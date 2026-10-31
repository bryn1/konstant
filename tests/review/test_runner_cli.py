"""Runner + CLI findings: F-01 (run level), F-05 (detached producer process), F-08 (catalog
edited mid-run), F-15 (max_parallel = 1), F-12 (phase token), F-23, F-24, F-25, F-26, F-27,
F-28, F-30."""
from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.cli.conftest import Workspace, free_port

REPO = Path(__file__).resolve().parents[2]
FAKE = f"{sys.executable} {REPO / 'tests' / 'fixtures' / 'fake_harness.py'} {{prompt_file}}"


@pytest.fixture()
def rws(tmp_path):
    """A runner workspace with projects/demo (git) and NO board."""
    w = Workspace(tmp_path)
    proj = tmp_path / "projects" / "demo"
    proj.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-C", str(proj), "-c", "user.email=t@example.com", "-c",
                        "user.name=t", *args], check=True)
    return w


def run(w, mode="", *extra, task="[type:code] add greet()", env_extra=None):
    env = w.env(**({"FAKE_HARNESS_MODE": mode} if mode else {}), **(env_extra or {}))
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run", task, "--project",
                          "demo", "--harness", FAKE, *extra], capture_output=True, text=True,
                         env=env, timeout=600, cwd=str(w.home))
    runs = sorted((w.home / "var" / "runs").iterdir())
    return res, runs[-1]


def out_of(run_dir: Path) -> Path:
    return Path(json.loads((run_dir / "record.json").read_text())["out"])


def _kill_daemons(out: Path):
    pidfile = out / ".tmp" / "daemon.pid"
    for line in (pidfile.read_text().split() if pidfile.exists() else []):
        try:
            os.kill(int(line), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass


def test_F01_declined_quotes_do_not_turn_a_failed_run_met(rws):
    res, rd = run(rws, "declined")
    assert res.returncode != 0, res.stderr


def test_F05_a_detached_producer_process_cannot_flip_the_verdict(rws):
    res, rd = run(rws, "daemon")
    out = out_of(rd)
    try:
        flipped = [f.name for f in out.glob("*verdict*.md") if "flipped" in f.read_text()]
        assert not flipped, flipped
        assert res.returncode != 0, res.stderr
    finally:
        _kill_daemons(out)


def test_F08_a_producer_cannot_rewrite_the_testers_profile_mid_run(rws):
    shutil.copytree(REPO / "catalog", rws.home / "catalog")
    res, rd = run(rws, "catalog")
    assert "INJECTED-BY-CODER" in (rws.home / "catalog" / "agents" / "tester.md").read_text()
    hit = [p.name for p in (rd / "prompts").glob("*tester*") if "INJECTED-BY-CODER" in
           p.read_text()]
    assert not hit, hit


def test_F15_max_parallel_one_attributes_each_phase(rws):
    with open(rws.home / "konstant.toml", "a") as fh:
        fh.write("\n[harness]\nmax_parallel = 1\n")
    res, rd = run(rws)
    assert res.returncode == 0, res.stderr
    tester = json.loads(next((rd / "phases").glob("*-tester-c1.json")).read_text())
    assert "group" not in tester and tester["created"] == ["TEST-verdict.md"], tester


def test_F26_a_small_task_runs_in_the_project_dir(rws):
    harness = (f"{sys.executable} -c \"import os; print('CWD=' + os.getcwd())\" "
               "{prompt_file}")
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run", "what is the board?",
                          "--project", "demo", "--harness", harness], capture_output=True,
                         text=True, env=rws.env(), timeout=60, cwd=str(rws.home))
    assert res.returncode == 0, res.stderr
    rd = sorted((rws.home / "var" / "runs").iterdir())[-1]
    log = (rd / "phases" / "small.log").read_text()
    assert f"CWD={rws.home / 'projects' / 'demo'}" in log, log


def test_F26_a_small_task_bound_to_a_job_is_refused(rws):
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run", "what is the board?",
                          "--project", "demo", "--job", "7", "--harness", FAKE],
                         capture_output=True, text=True, env=rws.env(), timeout=60,
                         cwd=str(rws.home))
    assert res.returncode == 2 and "small" in res.stderr, res.stderr


def test_F28_one_run_per_project_at_a_time(rws, tmp_path):
    marker = tmp_path / "slow.pid"
    slow = (f"{sys.executable} -c \"import os,time; open('{marker}','w').write(str(os.getpid()));"
            f" time.sleep(60)\" {{prompt_file}}")
    first = subprocess.Popen([sys.executable, "-m", "konstant", "task", "run", "[type:code] x",
                              "--project", "demo", "--harness", slow], env=rws.env(),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             cwd=str(rws.home))
    try:
        deadline = time.time() + 30
        while not marker.exists() and time.time() < deadline:
            time.sleep(0.1)
        second = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                                 "[type:code] y", "--project", "demo", "--harness", FAKE],
                                capture_output=True, text=True, env=rws.env(), timeout=60,
                                cwd=str(rws.home))
        assert second.returncode == 2 and "another task run" in second.stderr, second.stderr
    finally:
        first.send_signal(signal.SIGTERM)
        first.communicate(timeout=30)


@pytest.fixture(scope="module")
def bws(tmp_path_factory):
    w = Workspace(tmp_path_factory.mktemp("ws"))
    w.ok("board", "init")
    w.ok("board", "start")
    w.ok("project", "add", "demo")
    yield w
    w.run("board", "stop")


def test_F12_a_phase_acts_as_worker(bws):
    brief = bws.write("b.md", "x\nDoD: it works\nPROBE: test -d projects/demo => ^ok$\n")
    env = bws.env(KONSTANT_IN_TASK="1", KONSTANT_ROLE="worker")
    res = bws.run("job", "add", "T: by a phase", "--project", "demo", "--type", "code",
                  "--brief", brief, "--json", env=env)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["requested_by"] == "worker"
    refused = bws.run("--as", "orchestrator", "job", "list", env=env)
    assert refused.returncode == 1 and "inside a task run" in refused.stderr


def test_F27_board_tokens_defaults_to_the_owner(bws):
    res = bws.run("board", "tokens")
    assert res.returncode == 0 and "owner" in res.stdout, res.stderr


def test_F30_job_add_warns_about_a_refused_probe(bws):
    brief = bws.write("b2.md", "x\nDoD: it works\nPROBE: cat /etc/passwd => root\n")
    res = bws.run("job", "add", "T: lint", "--project", "demo", "--type", "code", "--brief",
                  brief)
    assert res.returncode == 0 and "PROBE REFUSED" in res.stderr, res.stderr


def test_F23_board_stop_does_not_signal_a_foreign_pid(fresh):
    victim = subprocess.Popen(["sleep", "30"])
    try:
        (fresh.home / "var").mkdir(parents=True, exist_ok=True)
        (fresh.home / "var" / "board.pid").write_text(f"{victim.pid}\n")
        fresh.run("board", "stop")
        time.sleep(0.3)
        assert victim.poll() is None, "board stop killed an unrelated process"
    finally:
        victim.kill()
        victim.wait()


def test_F24_board_serve_refuses_a_public_host(fresh):
    fresh.ok("board", "init")
    try:
        res = subprocess.run([sys.executable, "-m", "konstant", "board", "serve", "--host",
                              "0.0.0.0", "--port", str(free_port())], capture_output=True,
                             text=True, env=fresh.env(), timeout=15, cwd=str(fresh.home))
    except subprocess.TimeoutExpired:
        pytest.fail("board serve bound a non-loopback host")
    assert res.returncode == 1 and "allow_remote" in res.stderr


def test_F25_var_and_db_are_private_under_umask_002(fresh):
    old = os.umask(0o002)
    try:
        fresh.ok("board", "init")
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(fresh.home / "var").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(fresh.home / "var" / "board.db").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(fresh.home / "var" / "runs").st_mode) & 0o077 == 0
