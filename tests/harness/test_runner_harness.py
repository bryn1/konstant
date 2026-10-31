"""The runner with named adapters (no model): each phase runs on its type's harness, the manifest
records which, and konstant's own guarantees (worker role, the subreaper, the verdict pin) hold
whatever the harness. Fake `dsh`/`codex` binaries wrap the deterministic fake harness."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tests.cli.conftest import Workspace

REPO = Path(__file__).resolve().parents[2]
FAKE = REPO / "tests" / "fixtures" / "fake_harness.py"
STUB = REPO / "tests" / "fixtures" / "stub_dsh.py"


@pytest.fixture()
def rws(tmp_path):
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    proj = w.home / "projects" / "demo"
    proj.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-C", str(proj), "-c", "user.email=t@example.com", "-c",
                        "user.name=t", *args], check=True)
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    for name in ("dsh", "codex"):           # the adapter's argv ends in `-`: prompt on stdin
        p = bindir / name
        # a run composes dsh's layers first (`--dump-config`, fail closed): the stub answers
        dump = (f'case " $* " in *" --dump-config "*) exec {sys.executable} {STUB} "$@";; esac\n'
                if name == "dsh" else "")
        p.write_text(f"#!/bin/sh\n{dump}echo \"{name} $KONSTANT_ROLE\" >> \"$KONSTANT_RUN/who.log\"\n"
                     f"exec {sys.executable} {FAKE}\n")
        p.chmod(0o755)
    w.bindir = bindir
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\nmodel = "m-coder"\n'
                    '[harness.types.review]\nname = "codex"\nmodel = "m-review"\n')
    w.ok("agents", "sync")                  # .dsh/konstant.patch.yml: a dsh run composes it
    return w


def run(w, mode=""):
    env = w.env(PATH=f"{w.bindir}:{os.environ['PATH']}",
                **({"FAKE_HARNESS_MODE": mode} if mode else {}))
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet()", "--project", "demo"], capture_output=True,
                         text=True, env=env, timeout=600, cwd=str(w.home))
    return res, sorted((w.home / "var" / "runs").iterdir())[-1]


def test_each_phase_runs_on_its_types_harness(rws):
    res, rd = run(rws)
    assert res.returncode == 0, res.stderr
    by_agent = {}
    for m in (rd / "phases").glob("*.json"):
        d = json.loads(m.read_text())
        by_agent[d["agent"]] = (d["harness"], d["model"])
    assert by_agent["coder"] == ("dsh", "m-coder")
    assert by_agent["reviewer"] == ("codex", "m-review")
    assert by_agent["orchestrator"] == ("dsh", "m-coder")            # close-out: the default
    who = (rd / "who.log").read_text().split("\n")
    assert {ln.split()[1] for ln in who if ln} == {"worker"}             # every phase is worker
    assert (rd / "tmp").is_dir()                                         # codex's TMPDIR


def test_reaper_and_verdict_pin_hold_under_a_named_adapter(rws):
    """REVIEW F-05 under dsh/codex: a detached producer process cannot flip the verdict."""
    res, rd = run(rws, "daemon")
    out = Path(json.loads((rd / "record.json").read_text())["out"])
    try:
        flipped = [f.name for f in out.glob("*verdict*.md") if "flipped" in f.read_text()]
        assert not flipped and res.returncode != 0, (flipped, res.stderr[-500:])
    finally:
        pidfile = out / ".tmp" / "daemon.pid"
        for line in (pidfile.read_text().split() if pidfile.exists() else []):
            # under konstant's jail the pid is one of the jail's own pid namespace (and the
            # watcher died with it): kill only a host process that IS this run's watcher
            try:
                cmd = Path(f"/proc/{int(line)}/cmdline").read_bytes()
                if str(out).encode() in cmd:
                    os.kill(int(line), signal.SIGKILL)
            except (OSError, ValueError):
                pass


def test_harness_flag_names_an_adapter_for_every_phase(rws):
    """`task run --harness dsh` runs EVERY phase on the dsh adapter (its
    argv, env and jail), overriding the per-type rows; a template still works as before."""
    env = rws.env(PATH=f"{rws.bindir}:{os.environ['PATH']}")
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet()", "--project", "demo", "--harness", "dsh"],
                         capture_output=True, text=True, env=env, timeout=600, cwd=str(rws.home))
    assert res.returncode == 0, res.stderr[-2000:]
    rd = sorted((rws.home / "var" / "runs").iterdir())[-1]
    seen = {json.loads(m.read_text())["agent"]: json.loads(m.read_text())["harness"]
            for m in (rd / "phases").glob("*.json")}
    assert set(seen.values()) == {"dsh"} and "reviewer" in seen, seen
