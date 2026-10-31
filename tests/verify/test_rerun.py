"""rerun.py: scrubbed env, process-group kill on timeout, commit-ancestor rule."""
from __future__ import annotations

import os
import subprocess
import time

from konstant.verify import rerun
from tests.verify.conftest import git


def test_green_exit_zero(tmp_path):
    r = rerun.rerun({"verify_cmd": "echo hi"}, tmp_path)
    assert r["ran"] and r["exit"] == 0 and r["ok"] is True and "hi" in r["output"]


def test_nonzero_exit_red(tmp_path):
    r = rerun.rerun({"verify_cmd": "echo bad; exit 3"}, tmp_path)
    assert r["exit"] == 3 and r["ok"] is False


def test_runs_in_the_project_dir_green(tmp_path):
    (tmp_path / "here.txt").write_text("x")
    assert rerun.rerun({"verify_cmd": "test -f here.txt"}, tmp_path)["ok"] is True
    assert rerun.rerun({"verify_cmd": "test -f gone.txt"}, tmp_path)["ok"] is False


def test_env_is_scrubbed_red(tmp_path, monkeypatch):
    monkeypatch.setenv("KONSTANT_HOME", "/h")
    monkeypatch.setenv("SOME_API_KEY", "k")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("KEEP_ME", "yes")
    r = rerun.rerun({"verify_cmd": 'echo "[$KONSTANT_HOME|$SOME_API_KEY|$DB_PASSWORD|$KEEP_ME]"'},
                    tmp_path)
    assert "[|||yes]" in r["output"]


def test_timeout_kills_the_whole_group_red(tmp_path):
    marker = tmp_path / "child-alive"
    cmd = f"(sleep 2; touch {marker}) & sleep 30"
    t = time.monotonic()
    r = rerun.rerun({"verify_cmd": cmd}, tmp_path, timeout=0.5)
    assert r["timed_out"] and r["ok"] is None and time.monotonic() - t < 10
    time.sleep(2.5)
    assert not marker.exists()                 # the background child died with the group


def test_skipped_without_cmd_or_dir_green(tmp_path):
    assert rerun.rerun({}, tmp_path)["ran"] is False
    r = rerun.rerun({"verify_cmd": "true"}, tmp_path / "missing")
    assert r["ran"] is False and r["ok"] is None and "no directory" in r["skipped"]


def _repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a").write_text("1")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "one")
    first = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout.strip()
    (tmp_path / "a").write_text("2")
    git(tmp_path, "commit", "-qam", "two")
    return first


def test_commit_ancestor_of_head_passes_green(tmp_path):
    first = _repo(tmp_path)
    r = rerun.rerun({"verify_cmd": "true", "commit": first}, tmp_path)
    assert r["commit_ok"] is True and r["ok"] is True


def test_commit_not_ancestor_fails_without_running_red(tmp_path):
    _repo(tmp_path)
    git(tmp_path, "checkout", "-q", "-b", "side", "HEAD~1")
    (tmp_path / "b").write_text("x")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "side")
    side = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    git(tmp_path, "checkout", "-q", "main")
    r = rerun.rerun({"verify_cmd": "touch ran", "commit": side}, tmp_path)
    assert r["commit_ok"] is False and r["ok"] is False and not r["ran"]
    assert not (tmp_path / "ran").exists()


def test_unknown_commit_and_non_repo_fail_red(tmp_path):
    assert rerun.rerun({"verify_cmd": "true", "commit": "deadbeef"}, tmp_path)["ok"] is False
    _repo(tmp_path)
    assert rerun.rerun({"verify_cmd": "true", "commit": "deadbeef"}, tmp_path)["ok"] is False
    assert rerun.rerun({"verify_cmd": "true", "commit": "-x"}, tmp_path)["ok"] is False
    assert os.path.isdir(tmp_path)
