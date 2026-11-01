"""Factory-mode test harness (docs/LEVEL5.md 2.1-2.4, wave L5-2): the holdout workspace of
tests/holdout/conftest.py (board running, project `greeter` = the TARGET, a `code` job with the
visible DoD), plus stand-ins for every harness CLI on PATH - tests/fixtures/stub_dsh.py as `dsh`,
tests/fixtures/stub_cli.py as `claude`, `codex` and `gemini` - so a holdout job runs through each
REAL adapter (its argv, env, per-phase home and confinement) with the fake harness playing the
phase. HOME is a temp dir holding a fake credential file per CLI and a planted file beside it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures import stub_cli
from tests.holdout.conftest import H1, H2, REPO, TASK, make_ws

FAKE = f"{sys.executable} {REPO / 'tests' / 'fixtures' / 'fake_harness.py'} {{prompt_file}}"
# the harness paths a factory phase can take: four adapters and an explicit command template
HARNESSES = ("claude", "codex", "gemini", "dsh", "command")
CRED = {"claude": ".claude/.credentials.json", "codex": ".codex/auth.json"}


def harness_arg(name: str) -> str:
    return FAKE if name == "command" else name


def make_fws(tmp: Path):
    w = make_ws(tmp)
    try:
        for name in ("claude", "codex", "gemini"):
            stub_cli.install(w.bindir, name)
        home = tmp / "home"
        for rel in (*CRED.values(), ".claude/planted", ".codex/planted", ".ssh/id_planted"):
            (home / rel).parent.mkdir(parents=True, exist_ok=True)
            (home / rel).write_text("FAKE-SECRET-" + rel.replace("/", "-") + "\n")
    except BaseException:
        w.stop_board()                             # never leave a board behind a failed setup
        raise
    w.fake_home = home
    return w


def run(w, harness: str, job: int, mode: str = "", timeout: int = 900, **extra):
    env = w.henv(HOME=str(w.fake_home),
                 **({"FAKE_HARNESS_MODE": mode} if mode else {}), **extra)
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run", TASK, "--job",
                          str(job), "--harness", harness_arg(harness)], capture_output=True,
                         text=True, env=env, timeout=timeout, cwd=str(w.home))
    runs = sorted((w.home / "var" / "runs").iterdir()) if (w.home / "var" / "runs").is_dir() \
        else []
    return res, (runs[-1] if runs else None)


def sealed_job(w, brief=None) -> int:
    jid = w.add_job(*( [brief] if brief else []))
    res = w.seal(jid, H1, H2)
    assert res.returncode == 0, res.stderr
    return jid


def logs(rd: Path) -> str:
    return "".join(p.read_text(errors="replace") for p in sorted(rd.glob("phases/*.log")))


def stub_starts(rd: Path) -> list:
    """The `stub-cli:` lines of a run's phase logs (tests/fixtures/stub_cli.py)."""
    return [json.loads(ln[len("stub-cli: "):]) for ln in logs(rd).splitlines()
            if ln.startswith("stub-cli: ")]


def git_out(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}).stdout.strip()


@pytest.fixture()
def fws(tmp_path):
    w = make_fws(tmp_path)
    yield w
    w.stop_board()
