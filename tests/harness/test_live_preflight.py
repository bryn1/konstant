"""`konstant doctor --live-preflight` and the stub dsh's bash-tool environment (wave L5-L).

The L5-F2b live run broke because a variable konstant set for git (GIT_CONFIG_KEY_0) never
reached the shell of a dsh phase: dsh's bash tool drops every name matching
/KEY|PASSWORD|SECRET|TOKEN/i. The offline suite stayed green because the stub dsh passed its
environment through. Now:
  - the stub's model commands get dsh's own tool environment (stub_dsh.tool_env, measured from
    inside a real phase by the pre-flight: docs/LEVEL5.md "L5-L as built");
  - the pre-flight runs ONE jailed phase through the real runner and adapter with a scripted
    endpoint (no model) and reports from inside the phase's shell; with the stub's endpoint mode
    it runs here, in CI, against the same environment rules.
The red twin plants the L5-F2b shape (a GIT_CONFIG triple konstant would hand the phase) and
the pre-flight must fail on it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from konstant import jail
from tests.cli.conftest import Workspace
from tests.fixtures import stub_dsh

needs_jail = pytest.mark.skipif(not jail.available(), reason="bubblewrap cannot run here")


def make(tmp_path):
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n')
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub_dsh.install(bindir)
    w.path = f"{bindir}:/usr/bin:/bin"
    w.ok("board", "init")
    w.ok("agents", "sync", env=w.env(PATH=w.path))                # pins the stub (K-01)
    return w


def preflight(w, **extra) -> tuple:
    env = w.env(PATH=w.path, STUB_DSH_THEN="endpoint", KONSTANT_ENV_PASSTHROUGH="STUB_*",
                **extra)
    r = subprocess.run([sys.executable, "-m", "konstant", "--json", "doctor", "--live-preflight"],
                       capture_output=True, text=True, env=env, timeout=300, cwd=str(w.home))
    rows: dict = {}
    for c in json.loads(r.stdout)["checks"]:
        rows.setdefault(c["check"], []).append(c["status"])
    return r, rows


def test_the_stub_tool_env_is_dshs():
    """stub_dsh.tool_env: the harness env minus credential-shaped and DSH_* names, plus dsh's
    overrides and its own DSH_* facts (dsh 0.2.2 bash tool)."""
    keep = {"PATH": "/usr/bin", "KONSTANT_HOME": "/w", "GIT_CONFIG_PARAMETERS": "'a.b='",
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "", "KONSTANT_ENDPOINT_KEY": "unused", "A_SECRET": "s",
            "my_password": "p", "GH_TOKEN": "t", "DSH_PLANTED": "x", "DSH_HOME": "/elsewhere"}
    saved = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(keep, DSH_HOME="/h")
        env = stub_dsh.tool_env("headless")
    finally:
        os.environ.clear()
        os.environ.update(saved)
    for gone in ("GIT_CONFIG_KEY_0", "KONSTANT_ENDPOINT_KEY", "A_SECRET", "my_password",
                 "GH_TOKEN", "DSH_PLANTED"):
        assert gone not in env, gone
    for kept in ("PATH", "KONSTANT_HOME", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
                 "GIT_CONFIG_VALUE_0"):
        assert env[kept] == keep[kept], kept
    assert env["DSH_HOME"] == "/h" and env["DSH_SHELL"] == "1" and env["DSH_PROFILE"] == \
        "headless" and env["DSH_SESSION_ID"].startswith("session-")
    assert env["TERM"] == "dumb" and env["GIT_PAGER"] == "cat" and env["NO_COLOR"] == "1"


@needs_jail
def test_live_preflight_passes_through_the_real_runner_green(tmp_path):
    w = make(tmp_path)
    r, rows = preflight(w)
    assert r.returncode == 0, r.stdout + r.stderr
    for name in ("live dsh layers", "live phase", "live prompt", "in phase: env-git-config",
                 "in phase: git-rev-parse", "in phase: git-status", "in phase: git-config-ro",
                 "in phase: target-ro", "in phase: token-own", "in phase: token-other",
                 "in phase: sealed", "in phase: sealed-canary", "in phase: own-dir",
                 "in phase: other-dir", "in phase: judged-input", "in phase: judge",
                 "in phase: verdict", "live pin"):
        assert rows.get(name) and set(rows[name]) == {"PASS"}, (name, r.stdout)
    # it leaves nothing behind: no throwaway target or clone, no run dir, no canary
    assert not [p for p in (w.home / "projects").iterdir()], list((w.home / "projects").iterdir())
    assert not (w.home / "var" / "runs").is_dir() or not list((w.home / "var" / "runs").iterdir())
    store = w.home / "var" / "holdout"
    assert not store.exists() or not list(store.iterdir())


# the L5-F2a code (433d2a1) that the L5-F2b live run found: the credential reset as a
# GIT_CONFIG_COUNT/KEY_0/VALUE_0 triple, planted back into the konstant process
F2A = """
from konstant import confinement
_orig = confinement.Confinement.withheld_env
def withheld_env(self, env):
    out = _orig(self, env)
    if any(w.startswith("$") for w in self.withhold):
        out.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="credential.helper",
                   GIT_CONFIG_VALUE_0="")
    return out
confinement.Confinement.withheld_env = withheld_env
"""


@needs_jail
def test_live_preflight_catches_a_variable_dsh_drops_red(tmp_path):
    """The L5-F2b class: konstant hands the phase a variable dsh's bash tool drops (the L5-F2a
    GIT_CONFIG triple: the *KEY* name goes, git then refuses every call and the judge inside
    hashes the clone without git). The pre-flight must FAIL, naming it."""
    w = make(tmp_path)
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(F2A)
    r, rows = preflight(w, PYTHONPATH=f"{site}:{os.environ.get('PYTHONPATH', '')}")
    assert r.returncode != 0, r.stdout
    assert rows.get("in phase: env-git-config") == ["FAIL"], r.stdout
    assert rows.get("in phase: git-rev-parse") == ["FAIL"], r.stdout
    assert rows.get("in phase: git-status") == ["FAIL"], r.stdout
    # konstant's own git view drops every inherited GIT_CONFIG_* (8f6423b), so its judge still
    # pins with git inside the phase and the pin matches outside: the model's git is what broke
    assert rows.get("live pin") == ["PASS"], r.stdout


def test_live_preflight_refuses_a_non_dsh_harness(tmp_path):
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    r = w.run("doctor", "--live-preflight")
    assert r.returncode == 1 and "starts a dsh phase only" in r.stdout, r.stdout


def test_doctor_without_the_flag_starts_no_phase(tmp_path):
    w = make(tmp_path)
    r = w.run("doctor", env=w.env(PATH=w.path))
    assert "in phase:" not in r.stdout and "live pin" not in r.stdout, r.stdout
