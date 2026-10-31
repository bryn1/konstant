"""`konstant dsh APP` refuses to start a session it cannot vouch for (G-01/G-02/G-05):
the session is not jailed, so a foreign layer (a dsh launcher forcing its
own DSH_HOME, a layer planted in the session home), a composition it cannot read, or generated
surfaces that differ from the catalog refuse the start, exit 1 (fail closed). The dsh on PATH is
tests/fixtures/stub_dsh.py (dsh's dump rules, no model)."""
from __future__ import annotations

import json

import pytest

from tests.cli.conftest import Workspace
from tests.fixtures import stub_dsh


@pytest.fixture()
def dws(tmp_path, home):
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n')
    w.ok("board", "init")
    w.ok("agents", "sync")
    return w


def start(w, tmp_path, *args, **env):
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir(exist_ok=True)
    stub_dsh.install(fakebin)
    log = tmp_path / "dsh.log"
    log.unlink(missing_ok=True)
    e = w.env(PATH=f"{fakebin}:/usr/bin:/bin", STUB_DSH_LOG=str(log), **env)
    res = w.run("dsh", *(args or ("web", "--port", "3999")), env=e)
    recs = [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []
    return res, [r for r in recs if "dump" in r], [r for r in recs if "argv" in r]


def session_home(w):
    return w.home / "var" / "harness" / "dsh" / "session" / "home"


def test_a_launcher_forcing_its_own_home_refuses_the_session(dws, tmp_path):
    op = tmp_path / "elsewhere"
    (op / "profiles" / "web").mkdir(parents=True)
    (op / "profiles" / "web" / "cordis.patch.yml").write_text("- id: approval\n  config: {}\n")
    res, dumps, runs = start(dws, tmp_path, STUB_DSH_DUMP="forced", STUB_DSH_FORCED_HOME=str(op))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "refused" in res.stderr and str(op) in res.stderr
    assert not runs, "dsh was started despite the foreign layer"
    real = [d for d in dumps if "--patch" in d["dump"]]
    assert real and real[0]["dump"][:3] == ["--profile", "web", "--patch"]
    assert str(dws.home / ".dsh" / "konstant-session.patch.yml") in real[0]["dump"]


def test_workspace_layers_only_start_the_session(dws, tmp_path):
    res, _dumps, runs = start(dws, tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "dsh started" in res.stdout and "refused" not in res.stderr
    got = runs[0]
    assert got["argv"][:2] == ["--profile", "web"] and got["argv"][-2:] == ["--port", "3999"]
    assert got["DSH_HOME"] == str(session_home(dws))


@pytest.mark.parametrize("mode", ["empty", "fail"])
def test_an_unreadable_composition_refuses_the_session(dws, tmp_path, mode):
    """G-05: was a warning and the session started (an empty dump under Node 20)."""
    res, _dumps, runs = start(dws, tmp_path, STUB_DSH_DUMP=mode)
    assert res.returncode == 1 and not runs, res.stdout + res.stderr
    assert "refused" in res.stderr
    if mode == "empty":
        assert "could not read the composition" in res.stderr and "Node.js >= 22" in res.stderr


def test_dry_run_does_not_compose(dws, tmp_path):
    """--dry-run stays side-effect free: no dsh call at all."""
    res, dumps, runs = start(dws, tmp_path, "--dry-run", "web")
    assert res.returncode == 0 and not dumps and not runs, res.stderr
