"""Second security review: the F-01, F-05 and F-08 attack modes of the review's
adversarial fake harness, run through `task run --harness dsh` - the real dsh adapter (argv,
generated patch, fresh per-phase home, preflight, konstant's jail) with tests/fixtures/stub_dsh.py
as the `dsh` binary, whose tool actions are the fake harness's (no model). Plus the dsh-specific
path G-01 opened: a layer one phase plants that a later (verifying) phase loads, and a layer a
phase plants into the operator's session home.

F-01/F-05/F-08 hold before the fix too (the DoD rules, the jail's pid namespace and its read-only
catalog/ do not depend on the harness); the G-01 runs were red before it."""
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


@pytest.fixture()
def dws(tmp_path):
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    shutil.copytree(REPO / "catalog", w.home / "catalog")
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n')
    w.ok("board", "init")
    w.ok("agents", "sync")
    proj = w.home / "projects" / "demo"
    proj.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-C", str(proj), "-c", "user.email=t@example.com", "-c",
                        "user.name=t", *args], check=True)
    w.bindir = tmp_path / "fakebin"
    w.bindir.mkdir()
    stub_dsh.install(w.bindir)
    return w


def run(w, mode: str = "", **extra):
    env = w.env(PATH=f"{w.bindir}:{os.environ['PATH']}", STUB_DSH_THEN="fake",
                **({"FAKE_HARNESS_MODE": mode} if mode else {}), **extra)
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet()", "--project", "demo", "--harness", "dsh"],
                         capture_output=True, text=True, env=env, timeout=600, cwd=str(w.home))
    rd = sorted((w.home / "var" / "runs").iterdir())[-1]
    return res, rd


def out_of(rd: Path) -> Path:
    return Path(json.loads((rd / "record.json").read_text())["out"])


def phases_ran_on_dsh(rd: Path) -> set:
    return {json.loads(m.read_text())["harness"] for m in (rd / "phases").glob("*.json")}


def test_dsh_path_an_honest_run_is_met(dws):
    """The twin: the same machinery lets honest work through."""
    res, rd = run(dws)
    assert res.returncode == 0, res.stderr[-2000:]
    assert phases_ran_on_dsh(rd) == {"dsh"}


def test_F01_on_dsh_declined_quotes_do_not_turn_a_failed_run_met(dws):
    res, rd = run(dws, "declined")
    assert phases_ran_on_dsh(rd) == {"dsh"}
    assert res.returncode != 0, res.stderr[-2000:]
    assert "task: MET -" not in res.stderr


def test_F05_on_dsh_a_detached_producer_process_cannot_flip_the_verdict(dws):
    res, rd = run(dws, "daemon")
    out = out_of(rd)
    flipped = [f.name for f in out.glob("*verdict*.md") if "flipped" in f.read_text()]
    assert not flipped and res.returncode != 0, (flipped, res.stderr[-2000:])


@needs_jail
def test_F08_on_dsh_a_producer_cannot_rewrite_the_testers_profile(dws):
    before = (dws.home / "catalog" / "agents" / "tester.md").read_text()
    res, rd = run(dws, "catalog")
    assert (dws.home / "catalog" / "agents" / "tester.md").read_text() == before
    hit = [p.name for p in (rd / "prompts").glob("*tester*") if "INJECTED-BY-CODER" in
           p.read_text()]
    assert not hit, hit


def test_G01_on_dsh_a_planted_layer_cannot_pass_the_testers_phase(dws):
    """Every phase plants a profile layer in its DSH_HOME whose plugin makes a verifying phase
    write PASS. Before the fix the home was shared, so the tester's phase loaded it and the broken
    greet() ran MET with the verdict credited to the tester."""
    res, rd = run(dws, "broken",
                  STUB_DSH_ACTIONS="plant:$DSH_HOME/profiles/headless/cordis.patch.yml",
                  STUB_DSH_PAYLOAD="import os; os.environ['FAKE_PLANTED_PASS'] = '1'")
    out = out_of(rd)
    verdicts = {f.name: f.read_text().strip().splitlines()[-1] for f in out.glob("TEST-*.md")}
    assert res.returncode != 0, (verdicts, res.stderr[-2000:])
    assert all("FAIL" in v for v in verdicts.values()), verdicts


@needs_jail
def test_G01_on_dsh_a_phase_cannot_plant_into_the_operators_session(dws):
    """The P0: a phase wrote var/harness/dsh/session/home and the operator's next `konstant dsh`
    ran the planted plugin unjailed."""
    layer = dws.home / "var" / "harness" / "dsh" / "session" / "home" / "profiles" / "web"
    marker = dws.home / "SESSION-PAYLOAD-RAN"
    res, _rd = run(dws, STUB_DSH_ACTIONS=f"plant:{layer / 'cordis.patch.yml'}",
                   STUB_DSH_PAYLOAD=f"open({str(marker)!r}, 'a').write('x')")
    assert not (layer / "cordis.patch.yml").exists(), "a phase wrote the session home"
    start = dws.run("dsh", "web", env=dws.env(PATH=f"{dws.bindir}:{os.environ['PATH']}"))
    assert not marker.exists(), start.stdout + start.stderr
