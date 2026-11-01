"""Holdout test harness (docs/LEVEL5.md 3.9): a workspace with a real board, project `greeter`
(a git repo whose base greet() takes no argument), job 2 a `code` job with the visible DoD, and
scenario files written OUTSIDE the workspace. Phases run through the real dsh adapter with
tests/fixtures/stub_dsh.py as `dsh` (STUB_DSH_THEN=fake: the fake harness plays each phase), so
every phase is inside konstant's jail, as a job with holdouts requires."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from konstant import jail
from tests.cli.conftest import Workspace
from tests.fixtures import stub_dsh

REPO = Path(__file__).resolve().parents[2]
needs_jail = pytest.mark.skipif(not jail.available(), reason="bubblewrap cannot run here")

BASE_GREETER = '"""greeter: small greetings."""\n\n\ndef greet():\n    return "hello world"\n'
BRIEF = """add greet(name)

DoD:
- greet(name) greets the caller by name; greet('world') == 'hello world'
PROBE: test -f projects/greeter/greeter.py => ^ok$
VERIFY_CMD: python3 -c "from greeter import greet; assert greet('world') == 'hello world'"
"""
H1 = """SCENARIO: greet uses the caller's name
KIND: proof
RUN: python3 -c "from greeter import greet; print(greet('Ada'))"
EXPECT_EXIT: 0
EXPECT_OUT: hello Ada
HINT: names other than the default are used verbatim
"""
H2 = """SCENARIO: the default greeting still works
KIND: regression
RUN: python3 -c "from greeter import greet; print(greet().upper())"
EXPECT_EXIT: 0
EXPECT_OUT: HELLO WORLD
HINT: calling it without an argument keeps working
"""
TASK = "[type:code] add greet(name)"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c",
                           "user.name=t", *args], check=True, capture_output=True, text=True)


class HWS(Workspace):
    """A Workspace with the board running, the stub dsh on PATH and the greeter project."""

    def __init__(self, home: Path, src: Path, bindir: Path):
        super().__init__(home)
        self.src, self.bindir = src, bindir

    def henv(self, **extra) -> dict:
        return self.env(PATH=f"{self.bindir}:{os.environ['PATH']}", STUB_DSH_THEN="fake",
                        FAKE_HARNESS_MODULE="greeter", **extra)

    def scenario(self, name: str, text: str) -> Path:
        p = self.src / name
        p.write_text(text)
        return p

    def add_job(self, brief: str = BRIEF, *flags) -> int:
        b = self.src / f"brief-{len(list(self.src.glob('brief-*')))}.md"
        b.write_text(brief)
        res = self.ok("job", "add", "greet by name", "--project", "greeter", "--type", "code",
                      "--brief", b, "--json", *flags)
        return json.loads(res.stdout)["id"]

    def seal(self, job: int, *texts) -> subprocess.CompletedProcess:
        files = []
        for i, t in enumerate(texts):
            files += ["--file", self.scenario(f"j{job}-s{i}-{len(list(self.src.iterdir()))}"
                                              ".scenario", t)]
        return self.run("holdout", "add", job, *files)

    def task_run(self, mode: str = "", job: int = 2, timeout: int = 900, **extra):
        env = self.henv(**({"FAKE_HARNESS_MODE": mode} if mode else {}), **extra)
        res = subprocess.run([sys.executable, "-m", "konstant", "task", "run", TASK, "--job",
                              str(job), "--harness", "dsh"], capture_output=True, text=True,
                             env=env, timeout=timeout, cwd=str(self.home))
        runs = sorted((self.home / "var" / "runs").iterdir()) if \
            (self.home / "var" / "runs").is_dir() else []
        return res, (runs[-1] if runs else None)

    def json(self, *args) -> dict:
        res = self.run(*args, "--json")
        assert res.stdout.strip(), res.stderr
        return json.loads(res.stdout)


def make_ws(tmp: Path, verify_after_close: bool = True) -> HWS:
    (tmp / "w").mkdir()
    (tmp / "src").mkdir()
    (tmp / "bin").mkdir()
    w = HWS(tmp / "w", tmp / "src", tmp / "bin")
    shutil.copytree(REPO / "catalog", w.home / "catalog")
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n'
                    + ("" if verify_after_close else "[gate]\nverify_after_close = false\n"))
    stub_dsh.install(w.bindir)
    w.ok("board", "init")
    w.ok("agents", "sync")
    w.ok("board", "start")
    try:
        proj = w.home / "projects" / "greeter"
        proj.mkdir(parents=True)
        git(proj, "init", "-q", "-b", "main")
        (proj / "greeter.py").write_text(BASE_GREETER)
        (proj / "README.md").write_text("greeter\n")
        git(proj, "add", "-A")
        git(proj, "commit", "-qm", "base")
        w.ok("project", "add", "greeter")          # job 1 = the project root
    except BaseException:
        w.stop_board()                             # never leave a board behind a failed setup
        raise
    return w


@pytest.fixture()
def hws(tmp_path):
    w = make_ws(tmp_path)
    yield w
    w.stop_board()


@pytest.fixture()
def hws_manual(tmp_path):
    """verify_after_close = false: the test runs `verify` itself (A8, A9, A10)."""
    w = make_ws(tmp_path, verify_after_close=False)
    yield w
    w.stop_board()
