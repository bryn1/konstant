"""Shared fixtures: a tmp workspace home with a file, a git repo and a sqlite db."""
from __future__ import annotations

import os
import sqlite3
import subprocess

import pytest

from konstant.verify.shapes import Roots


# the identity by environment too: GIT_AUTHOR_* / GIT_COMMITTER_* in the caller's environment
# (the CI workflow sets them) beat `-c user.email`, and the probe tests read the author back
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t",
                    *args], check=True, capture_output=True, env={**os.environ, **IDENT})


@pytest.fixture()
def home(tmp_path):
    h = tmp_path / "home"
    (h / "d").mkdir(parents=True)
    (h / "f.txt").write_text("one\ntwo one\n")
    repo = h / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "f.txt").write_text("committed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "c1")
    con = sqlite3.connect(h / "data.db")
    con.execute("CREATE TABLE t (a, b)")
    con.execute("INSERT INTO t VALUES (1, 'x'), (2, NULL)")
    con.commit()
    con.close()
    return h


@pytest.fixture()
def roots(home):
    return Roots(home=home, paths=[home])


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    """A real board in a tmp workspace (the tests/cli harness), project `demo`."""
    from tests.cli.conftest import Workspace
    w = Workspace(tmp_path_factory.mktemp("vws"))
    w.ok("board", "init")
    w.ok("board", "start")
    w.ok("project", "add", "demo")
    (w.home / "projects" / "demo").mkdir(parents=True, exist_ok=True)
    yield w
    w.run("board", "stop")
