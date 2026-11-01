"""[confinement] host_agents (konstant/confinement.py; cli/dsh.py; wave L5-2b): found in L5-3's live
smoke - the orchestrator session is unjailed by design, and its model ran the host's own dsh
launcher, which loads the operator's personal agent home outside the workspace's composition.

Closed (and open without host_agents): `konstant dsh` puts refusing `dsh`, `claude`, `codex` and
`gemini` shims first on the session's PATH; a command the session runs by name gets exit 126 and
the host launcher never runs. Open with host_agents = true: no shims, the name resolves on the host
PATH (the documented risk). konstant itself drops the shim dir, so its own phases still find the
real CLIs. The dsh is tests/fixtures/stub_dsh.py; its `run:` action stands in for the model's shell
call; the "host launcher" is a planted script in a temp dir."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.cli.conftest import Workspace
from tests.fixtures import stub_dsh


def make(tmp_path, home, conf: str = ""):
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n' + conf)
    w.ok("board", "init")
    w.ok("agents", "sync")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    stub_dsh.install(fakebin)
    hostbin = tmp_path / "hostbin"              # the operator's own launcher, later on PATH
    hostbin.mkdir()
    marker = tmp_path / "HOST-LAUNCHER-RAN"
    (hostbin / "claude").write_text(f"#!/bin/sh\necho ran > {marker}\necho host-claude\n")
    (hostbin / "claude").chmod(0o755)
    return w, fakebin, hostbin, marker


def session(w, tmp_path, fakebin, hostbin, actions: str):
    log = tmp_path / "dsh.log"
    log.unlink(missing_ok=True)
    env = w.env(PATH=f"{fakebin}:{hostbin}:/usr/bin:/bin", STUB_DSH_LOG=str(log),
                STUB_DSH_ACTIONS=actions)
    res = w.run("dsh", "web", env=env)
    recs = [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []
    return res, recs


def acts(recs) -> dict:
    return {r["act"]: r for r in recs if "act" in r}


@pytest.mark.parametrize("conf", ["", '[confinement]\nprofile = "open"\n'])
def test_session_agent_clis_refused_by_name_red_host_launcher_never_runs(tmp_path, home, conf):
    w, fakebin, hostbin, marker = make(tmp_path, home, conf)
    res, recs = session(w, tmp_path, fakebin, hostbin, "run:dsh --version;run:claude -p hi")
    assert res.returncode == 0 and "dsh started" in res.stdout, res.stderr
    a = acts(recs)
    for name in ("run:dsh --version", "run:claude -p hi"):
        assert a[name]["rc"] == 126, a
        assert "host_agents = false" in a[name]["err"], a
    assert str(hostbin / "claude") in a["run:claude -p hi"]["err"]      # names what it shadows
    assert not marker.exists()
    shims = w.home / "var" / "harness" / "dsh" / "session" / "bin"
    assert sorted(p.name for p in shims.iterdir()) == ["claude", "codex", "dsh", "gemini"]
    started = [r for r in recs if "argv" in r]
    assert len(started) == 1                     # the session itself; `dsh` by name never ran


def test_host_agents_true_lets_the_session_reach_the_host_launcher_green(tmp_path, home):
    w, fakebin, hostbin, marker = make(
        tmp_path, home, '[confinement]\nprofile = "open"\nhost_agents = true\n')
    res, recs = session(w, tmp_path, fakebin, hostbin, "run:dsh --version;run:claude -p hi")
    assert res.returncode == 0, res.stderr
    a = acts(recs)
    assert a["run:dsh --version"]["rc"] == 0 and "0.2.1-stub" in a["run:dsh --version"]["out"]
    assert a["run:claude -p hi"]["rc"] == 0 and marker.exists(), a


def test_dry_run_shows_the_shim_first_on_path(tmp_path, home):
    w, fakebin, hostbin, _m = make(tmp_path, home)
    res = w.run("dsh", "--dry-run", "web", env=w.env(PATH=f"{fakebin}:{hostbin}:/usr/bin:/bin"))
    env = json.loads(res.stdout)["env"]
    shim = str(w.home / "var" / "harness" / "dsh" / "session" / "bin")
    assert env["PATH"].split(":")[0] == shim and env["KONSTANT_SHIM_DIR"] == shim
    (tmp_path / "b").mkdir()
    w2, *_ = make(tmp_path / "b", home, '[confinement]\nhost_agents = true\n')
    env2 = json.loads(w2.run("dsh", "--dry-run", "web").stdout)["env"]
    assert "KONSTANT_SHIM_DIR" not in env2 and "PATH" not in env2


def test_konstant_itself_drops_the_shim_dir(tmp_path):
    shim = str(tmp_path / "shim")
    code = ("import os\nfrom konstant.cli.main import drop_shim_dir\ndrop_shim_dir()\n"
            "print(os.environ['PATH'])\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "KONSTANT_SHIM_DIR": shim,
                              "PATH": f"{shim}:/usr/bin:/bin"}).stdout.strip()
    assert out == "/usr/bin:/bin"
