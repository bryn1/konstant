"""Verifier findings: F-02 (re-run alone settles PASS), F-04 (git shapes run repo config),
F-10 (closer shell as the verifier), F-13 (project paths), F-29 (var/ readable), F-35 (TOCTOU)."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from konstant import config
from konstant.gate.rules import judged
from konstant.verify import probe, verifier
from konstant.verify.shapes import Roots


def _row(source, matched=True):
    return {"line": "PROBE: test -e x => ^ok$", "source": source, "kind": "probe",
            "matched": matched, "error": None, "output": "ok"}


def test_F02_a_rerun_alone_does_not_settle_pass():
    verdict, reasons = verifier.settle([], {"ok": True, "ran": True, "exit": 0})
    assert verdict == "BLOCKED", reasons


def test_F02_closer_probes_alone_do_not_settle_pass():
    verdict, _r = verifier.settle([_row("closer")], {"ok": True, "ran": True, "exit": 0})
    assert verdict == "BLOCKED"


def test_F02_a_matched_dod_probe_settles_pass():
    assert verifier.settle([_row("dod")], {"ok": True, "ran": True, "exit": 0})[0] == "PASS"


def test_F02_a_noop_verify_cmd_is_refused_at_close(board):
    from tests.board.conftest import GOOD_EVIDENCE
    jid = board.add().json()["id"]
    board.call("orchestrator", "POST", f"/api/jobs/{jid}/claim")
    for cmd in ("true", ":", "exit 0", "echo 40 tests passed"):
        res = board.call("orchestrator", "POST", f"/api/jobs/{jid}/close",
                         {**GOOD_EVIDENCE, "verify_cmd": cmd})
        assert res.status_code == 422 and "checks nothing" in res.json()["detail"], cmd


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t",
                    *args], check=True, capture_output=True, text=True)


@pytest.fixture()
def evil_repo(tmp_path):
    """REVIEW F-04: a repo whose .git/config runs a command from a clean filter."""
    repo = tmp_path / "ws" / "projects" / "evil"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / ".gitattributes").write_text("*.txt filter=pwn\n")
    (repo / "a.txt").write_text("hello\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    marker = tmp_path / "PWNED"
    _git(repo, "config", "filter.pwn.clean", f"sh -c 'id > {marker}; cat'")
    os.utime(repo / "a.txt", (1577836800, 1577836800))      # stat-dirty: git re-reads it
    return repo, marker


def test_F04_git_status_probe_does_not_run_a_repo_filter(evil_repo):
    repo, marker = evil_repo
    roots = Roots.build(repo.parents[1], {})
    row = probe.run_line(f"PROBE: git -C {repo} status --porcelain => ^ M", roots)
    assert not marker.exists(), "a read-only probe executed a repo-configured filter"
    assert row["error"], row


def test_F04_ls_remote_probe_is_refused(evil_repo):
    repo, _m = evil_repo
    roots = Roots.build(repo.parents[1], {})
    row = probe.run_line(f"PROBE: git -C {repo} ls-remote origin HEAD => ^[0-9a-f]{{40}}", roots)
    assert row["error"] and "refused" in row["error"]


def test_F04_the_judge_does_not_run_a_repo_filter(evil_repo, tmp_path):
    repo, marker = evil_repo
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    (repo / "b.txt").write_text("new\n")
    state = judged.project_state({"project": str(repo), "out": str(tmp_path / "out"),
                                  "git_base": base})
    assert not marker.exists(), "konstant's own git read ran a repo-configured filter"
    assert "git/b.txt" in state


class _Client:
    def __init__(self, job, projects):
        self.job, self.projects, self.posted = job, projects, []

    def get(self, path, **_kw):
        return {"projects": self.projects} if path == "/api/projects" else self.job

    def post(self, path, body=None):
        self.posted.append((path, body))
        return {}


def _job(cmd, acceptance="DoD: it works\nPROBE: test -d projects/demo => ^ok$"):
    return {"id": 3, "display_id": "1.2", "status": "completed_unverified", "project": "demo",
            "acceptance": acceptance, "evidence": {"verify_cmd": cmd, "probes": []}}


def test_F10_os_separation_never_runs_the_closers_shell(tmp_path):
    home = tmp_path
    (home / "projects" / "demo").mkdir(parents=True)
    secrets = home / "var" / "secrets"
    secrets.mkdir(parents=True)
    for role in ("orchestrator", "worker"):
        (secrets / f"{role}.token").write_text("x\n")
        os.chmod(secrets / f"{role}.token", 0)
    if os.access(secrets / "worker.token", os.R_OK):
        pytest.skip("running as a user that reads mode-000 files (root)")
    marker = tmp_path / "PWNED-rerun"
    client = _Client(_job(f"touch {marker}"), [{"slug": "demo", "path": "projects/demo"}])
    res = verifier.verify_job(client, config.load(home), 3, dry_run=True)
    assert not marker.exists(), "the verifier ran the closer's command in OS-separation mode"
    assert "separation" in str(res["rerun"]["skipped"])


def test_F10_a_dod_verify_cmd_is_the_rerun_command(tmp_path):
    home = tmp_path
    (home / "projects" / "demo").mkdir(parents=True)
    ran = home / "projects" / "demo" / "dod-ran"         # the re-run may write its project dir
    closer = home / "projects" / "demo" / "closer-ran"
    acc = (f"DoD: it works\nVERIFY_CMD: touch {ran}\n"
           "PROBE: test -d projects/demo => ^ok$")
    client = _Client(_job(f"touch {closer}", acc), [{"slug": "demo", "path": "projects/demo"}])
    res = verifier.verify_job(client, config.load(home), 3, dry_run=True)
    assert ran.exists() and not closer.exists(), res["rerun"]


def test_F29_probes_cannot_read_var(tmp_path):
    (tmp_path / "var" / "secrets").mkdir(parents=True)
    (tmp_path / "var" / "secrets" / "verifier.token").write_text("abc\n")
    roots = Roots.build(tmp_path, {})
    with pytest.raises(ValueError):
        roots.locate("var/secrets/verifier.token")
    row = probe.run_line("PROBE: grep -c ^a var/secrets/verifier.token => ^0$", roots)
    assert row["error"] and "refused" in row["error"]


def test_F35_locate_returns_the_resolved_path(tmp_path):
    (tmp_path / "real.txt").write_text("x\n")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
    roots = Roots.build(tmp_path, {})
    assert roots.locate("link.txt") == str(tmp_path / "real.txt")


def test_F13_project_path_must_not_widen_the_roots(board):
    for bad in ("/", str(board.home.parent), str(board.home), str(board.home / "var"),
                os.path.expanduser("~")):
        res = board.call("owner", "POST", "/api/projects", {"slug": "rootx", "path": bad})
        assert res.status_code == 422, (bad, res.json())
    ok = board.call("owner", "POST", "/api/projects", {"slug": "fine", "path": "projects/fine"})
    assert ok.status_code == 200, ok.json()
