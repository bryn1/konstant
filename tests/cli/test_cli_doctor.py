"""`konstant doctor` (DESIGN §10) and `konstant board backup`: each check goes red on the planted
fault and names its fix; the green workspace exits 0."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from tests.cli.conftest import Workspace


def checks(res) -> dict:
    return {r["check"]: r for r in json.loads(res.stdout)["checks"]}


@pytest.fixture()
def ready(tmp_path):
    w = Workspace(tmp_path)
    (tmp_path / "konstant.toml").write_text(
        (tmp_path / "konstant.toml").read_text()
        + f'\n[harness]\ncommand = "{sys.executable} -c pass {{prompt}}"\n')
    w.ok("board", "init")
    w.ok("agents", "sync")
    return w


def test_doctor_green_on_a_ready_workspace(ready):
    res = ready.run("--json", "doctor")
    assert res.returncode == 0, res.stdout
    c = checks(res)
    assert {k for k, v in c.items() if v["status"] == "PASS"} >= {
        "python", "dependencies", "config", "var", "database", "tokens", "agents", "harness"}
    assert c["board"]["status"] == "INFO" and "board start" in c["board"]["detail"]
    assert c["role separation"]["detail"].startswith("procedural")


def test_doctor_red_on_an_uninitialised_folder(fresh):
    res = fresh.run("--json", "doctor")
    assert res.returncode == 1
    c = checks(res)
    assert c["database"]["status"] == "FAIL" and "board init" in c["database"]["detail"]
    assert c["tokens"]["status"] == "FAIL"


def test_doctor_red_on_a_loose_token_file(ready):
    os.chmod(ready.home / "var" / "secrets" / "worker.token", 0o644)
    res = ready.run("--json", "doctor")
    assert res.returncode == 1
    assert "worker.token is 0o644" in checks(res)["tokens"]["detail"]


def test_doctor_red_on_a_drifted_generated_file(ready):
    (ready.home / "CLAUDE.md").write_text("edited by hand\n")
    res = ready.run("--json", "doctor")
    assert res.returncode == 1 and "agents sync" in checks(res)["agents"]["detail"]


def test_doctor_red_on_a_pid_without_a_board(ready):
    # a process that IS this workspace's board (argv + cwd) but does not answer /health
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "konstant",
                                "board", "serve"], cwd=str(ready.home))
    try:
        (ready.home / "var" / "board.pid").write_text(f"{sleeper.pid}\n")
        res = ready.run("--json", "doctor")
        assert res.returncode == 1 and checks(res)["board"]["status"] == "FAIL"
    finally:
        sleeper.kill()
        sleeper.wait()


def test_doctor_warns_on_a_stale_pid_file(ready):
    # REVIEW F-23: a pid file naming an unrelated process (pid reuse) is stale, not a board
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (ready.home / "var" / "board.pid").write_text(f"{sleeper.pid}\n")
        res = ready.run("--json", "doctor")
        assert checks(res)["board"]["status"] == "WARN" and "stale" in checks(res)["board"]["detail"]
    finally:
        sleeper.kill()
        sleeper.wait()


def test_doctor_missing_harness_is_a_warning_not_a_failure(ready):
    toml = ready.home / "konstant.toml"
    toml.write_text(toml.read_text().replace(sys.executable, "no-such-agent-cli"))
    res = ready.run("--json", "doctor")
    assert res.returncode == 0
    c = checks(res)
    assert c["harness"]["status"] == "WARN" and "not found on PATH" in c["harness"]["detail"]


def test_doctor_red_on_a_bad_config(ready):
    (ready.home / "konstant.toml").write_text("[board]\nprot = 1\n")
    res = ready.run("--json", "doctor")
    assert res.returncode == 1 and "unknown key 'board.prot'" in checks(res)["config"]["detail"]


def test_backup_writes_a_0600_consistent_copy_and_refuses_to_overwrite(ready, tmp_path):
    dest = tmp_path / "copy.db"
    ready.ok("board", "backup", "--to", dest)
    assert oct(dest.stat().st_mode & 0o777) == "0o600"
    with sqlite3.connect(dest) as conn:
        assert conn.execute("select count(*) from tokens").fetchone()[0] == 9   # roles + identities
    res = ready.run("board", "backup", "--to", dest)
    assert res.returncode == 1 and "exists" in res.stderr
    ready.ok("board", "backup")
    assert len(list((ready.home / "var" / "backups").glob("board-*.db"))) == 1


def test_backup_without_a_db_fails(fresh):
    res = fresh.run("board", "backup")
    assert res.returncode == 1 and "board init" in res.stderr


def test_stranded_jobs_pure_red_and_green():
    from datetime import datetime, timezone
    from konstant.cli.doctor import stranded
    now = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    jobs = [{"display_id": "1.1", "status": "claimed", "updated_at": "2026-01-02T05:00:00Z"},
            {"display_id": "1.2", "status": "claimed", "updated_at": "2026-01-02T11:00:00Z"},
            {"display_id": "1.3", "status": "completed_unverified",
             "updated_at": "2026-01-02T10:00:00Z"},
            {"display_id": "1.4", "status": "completed_unverified",
             "updated_at": "2026-01-02T11:30:00Z"}]
    found = stranded(jobs, now)
    assert len(found) == 2
    assert found[0].startswith("job 1.1 claimed, no activity for 7h")
    assert found[1].startswith("job 1.3 waits 2h for a verdict")


def test_doctor_reports_stranded_jobs_on_a_running_board(ready):
    ready.ok("board", "start")
    try:
        res = ready.run("--json", "doctor")
        assert res.returncode == 0, res.stdout
        c = checks(res)
        assert c["board"]["status"] == "PASS" and c["stranded jobs"]["status"] == "PASS"
    finally:
        ready.run("board", "stop")
