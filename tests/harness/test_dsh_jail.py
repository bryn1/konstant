"""A dsh phase cannot read the privileged role tokens (dsh's own sandbox leaves reads open).

dsh's own sandbox confines writes only, so konstant runs every dsh phase in konstant.jail: the
workspace's var/secrets/ masked except the worker and viewer tokens, credential dirs masked, writes
only to the project, OUT, the relocated dsh home and a private /tmp. A fake `dsh` on PATH plays
the phase (the adapter's real argv, env and confinement; no model): it tries to read every token
and to write outside its boundary, and reports what it could do into the project dir.
Red without the jail (the fake reads every token); green with it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from konstant import jail
from tests.cli.conftest import Workspace

PROBE = r'''
import json, os, sys
ws = os.environ["KONSTANT_HOME"]
sec = os.path.join(ws, "var", "secrets")
res = {}
for role in ("owner", "orchestrator", "verifier", "worker", "viewer"):
    try:
        with open(os.path.join(sec, role + ".token")) as fh:
            res[role] = "READ" if fh.read().strip() else "EMPTY"
    except OSError as exc:
        res[role] = type(exc).__name__
for name, path in (("catalog", os.path.join(ws, "catalog", "x.md")),
                   ("var", os.path.join(ws, "var", "x.txt")),
                   ("toml", os.path.join(ws, "konstant.toml"))):
    try:
        with open(path, "a") as fh:
            fh.write("x")
        res["write-" + name] = "WROTE"
    except OSError as exc:
        res["write-" + name] = type(exc).__name__
sys.stdin.read()
with open(os.path.join(os.getcwd(), "probe.json"), "w") as fh:
    json.dump(res, fh)
'''


def _ws(tmp_path, jail_on: bool) -> Workspace:
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    for d in ("catalog", "projects/demo"):
        (w.home / d).mkdir(parents=True, exist_ok=True)
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n'
                    + ("" if jail_on else "[gate]\njail = false\n"))
    w.ok("board", "init")                     # the five role tokens in var/secrets/
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    probe = tmp_path / "probe.py"
    probe.write_text(PROBE)
    (bindir / "dsh").write_text(f"#!/bin/sh\nexec {sys.executable} {probe}\n")
    (bindir / "dsh").chmod(0o755)
    w.bindir = bindir
    return w


def _phase(w: Workspace) -> dict:
    """One phase exactly as the runner starts it: HarnessSet -> the dsh adapter."""
    code = (
        "import sys, json\n"
        "from pathlib import Path\n"
        "from konstant.config import load\n"
        "from konstant.gate.harness import HarnessSet\n"
        f"ws = Path({str(w.home)!r})\n"
        "cfg = load(ws)\n"
        "try:\n"
        "    hs = HarnessSet(cfg.data['harness'], ws, jail=bool(cfg.data['gate']['jail']))\n"
        "except TypeError:  # a HarnessSet without a jail: the red run\n"
        "    hs = HarnessSet(cfg.data['harness'], ws)\n"
        "run = ws / 'var' / 'runs' / 'r1'\n"
        "(run / 'out').mkdir(parents=True, exist_ok=True)\n"
        "from konstant.gate.harness import Harness\nkw = {'out': run / 'out'} if 'out' in Harness.run.__code__.co_varnames else {}\n"
        "r = hs.run('PROMPT', agent='coder', cwd=ws / 'projects' / 'demo', run_dir=run,\n"
        "           label='01-coder', **kw)\n"
        "print(json.dumps({'rc': r.rc, 'log': Path(r.log).read_text()}))\n")
    env = w.env(PATH=f"{w.bindir}:{os.environ['PATH']}")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                         timeout=120, cwd=str(w.home))
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    probe = w.home / "projects" / "demo" / "probe.json"
    assert probe.is_file(), out
    return json.loads(probe.read_text())


@pytest.mark.skipif(not jail.available(), reason="bubblewrap unavailable: the jail cannot run")
def test_dsh_phase_cannot_read_privileged_tokens(tmp_path):
    seen = _phase(_ws(tmp_path, jail_on=True))
    for role in ("owner", "orchestrator", "verifier"):
        assert seen[role] != "READ", (role, seen)             # masked by the jail
    assert seen["worker"] == "READ" and seen["viewer"] == "READ", seen   # its own role still works
    for k in ("write-catalog", "write-var", "write-toml"):
        assert seen[k] != "WROTE", (k, seen)                   # writes stay inside the boundary


def test_dsh_phase_without_the_jail_reads_every_token(tmp_path):
    """The other side ([gate] jail = false, or no bwrap): the gap is real and doctor says so."""
    seen = _phase(_ws(tmp_path, jail_on=False))
    assert seen["orchestrator"] == "READ", seen
