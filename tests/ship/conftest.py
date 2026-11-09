"""Ship test harness (docs/LEVEL5.md 5.6, wave L5-4): the holdout workspace of
tests/holdout/conftest.py (board running, project `greeter` = the TARGET, phases through the real
dsh adapter with the stub dsh and the fake harness), with a [ship] section, plus for the github
target a local BARE repository standing in for GitHub and the `gh` stand-in
(tests/fixtures/fake_gh.py) on a pinned path. Nothing here touches a network or a real GitHub."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures import fake_gh
from tests.holdout.conftest import H1, H2, make_ws

README_PROBE = "PROBE: test -f {workdir}/README.md => ^ok$"
# a second job's set (module farewell.py): its proof fails on a target that already has greeter
H3 = """SCENARIO: the second module greets by name
KIND: proof
RUN: python3 -c "from farewell import greet; print(greet('Bo'))"
EXPECT_EXIT: 0
EXPECT_OUT: hello Bo
HINT: the second module takes a name as well
"""
H4 = """SCENARIO: the first module still greets
KIND: regression
RUN: python3 -c "from greeter import greet; print(greet().title())"
EXPECT_EXIT: 0
EXPECT_OUT: Hello World
HINT: the first module keeps working
"""


def git_out(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}).stdout.strip()


def git_rc(repo, *args) -> int:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}).returncode


def commit_in(repo, name: str, text: str) -> str:
    (Path(repo) / name).write_text(text)
    for args in (("add", name), ("-c", "user.name=t", "-c", "user.email=t@example.com", "commit",
                                 "-qm", f"outside the factory: {name}")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                       env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull})
    return git_out(repo, "rev-parse", "HEAD")


class Ship:
    def __init__(self, w, gh=None, remote=None, gh_log=None):
        self.w, self.gh, self.remote, self.gh_log = w, gh, remote, gh_log
        self.target = w.home / "projects" / "greeter"

    def __getattr__(self, name):
        return getattr(self.w, name)

    def verified_job(self, mode: str = "", jtype: str = "code", scenarios=(H1, H2),
                     module: str = "greeter", **env) -> int:
        """A holdout job run by the fake harness (through the real dsh adapter) to `verified`."""
        from tests.holdout.conftest import BRIEF
        b = self.w.src / f"brief-{len(list(self.w.src.glob('brief-*')))}.md"
        b.write_text(BRIEF)
        jid = json.loads(self.w.ok("job", "add", "greet by name", "--project", "greeter",
                                   "--type", jtype, "--brief", b, "--json").stdout)["id"]
        sealed = self.w.seal(jid, *scenarios)
        assert sealed.returncode == 0, sealed.stderr
        run_env = self.w.henv()
        run_env.update(FAKE_HARNESS_MODULE=module, **env)
        if mode:
            run_env["FAKE_HARNESS_MODE"] = mode
        res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                              f"[type:{jtype}] add greet(name)", "--job", str(jid), "--harness",
                              "dsh"], capture_output=True, text=True, env=run_env, timeout=900,
                             cwd=str(self.w.home))
        assert res.returncode == 0, res.stderr[-3000:]
        job = self.w.json("job", "show", jid)
        assert job["status"] == "verified", job["status"]
        return jid

    def ship(self, *args, role: str = "") -> subprocess.CompletedProcess:
        pre = ["--as", role] if role else []
        return subprocess.run([sys.executable, "-m", "konstant", *pre, "ship", *map(str, args)],
                              capture_output=True, text=True, env=self.w.env(), timeout=900,
                              cwd=str(self.w.home))

    def job(self, jid) -> dict:
        return self.w.json("job", "show", jid)

    def commit(self, jid) -> str:
        return self.job(jid)["evidence"]["commit"]

    def ships(self) -> list:
        return self.w.json("ship", "list")

    def events(self) -> list:
        p = self.w.home / "var" / "factory" / "events.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []

    def gh_calls(self) -> list:
        p = Path(str(self.gh_log))
        return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []

    def pushes(self) -> list:
        p = Path(str(self.gh_log) + ".push")
        return p.read_text().splitlines() if p.is_file() else []

    def sql(self, q: str, args=()) -> None:
        con = sqlite3.connect(self.w.home / "var" / "board.db")
        try:
            con.execute(q, args)
            con.commit()
        finally:
            con.close()


def make_ship_ws(tmp: Path, ship: str = "", tail: str = "", github: bool = False,
                 refuse: str = "") -> Ship:
    w = make_ws(tmp)
    try:
        gh = remote = log = None
        extra = f'[ship]\npost_probes = ["{README_PROBE}"]\n' + ship
        if github:
            remote, log = tmp / "github" / "greeter.git", tmp / "gh.log"
            remote.parent.mkdir()
            subprocess.run(["git", "clone", "-q", "--bare", str(w.home / "projects" / "greeter"),
                            str(remote)], check=True, capture_output=True)
            gh = fake_gh.install(tmp / "pinned", remote, log, refuse)
            extra += (f'github_repo = "example-org/greeter"\nremote = "{remote}"\n'
                      f'gh = "{gh}"\n[factory]\ndefaults = {{ ship_target = "github" }}\n')
        w.stop_board()
        cfg = w.home / "konstant.toml"
        cfg.write_text(cfg.read_text() + extra + tail)
        w.ok("board", "start")
    except BaseException:
        w.stop_board()
        raise
    return Ship(w, gh, remote, log)


@pytest.fixture()
def sws(tmp_path):
    s = make_ship_ws(tmp_path)
    yield s
    s.w.stop_board()


@pytest.fixture()
def gws(tmp_path):
    s = make_ship_ws(tmp_path, github=True)
    yield s
    s.w.stop_board()
