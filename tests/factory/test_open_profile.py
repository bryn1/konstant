"""The open confinement profile keeps the integrity core on every harness path (konstant/
confinement.py; docs/CONCEPTS.md "Confinement profiles"; wave L5-2b).

A probe (tests/fixtures: the fake harness imports it through sitecustomize, so it runs as the
phase process, inside whatever konstant wrapped the phase in) tries what an open phase is meant to
do - read a planted ~/.ssh key, use a planted ssh-agent socket and credential variable, write a
planted path outside the workspace - and what no profile allows: read the sealed holdout store
and the other identities' tokens, write konstant's machinery and (factory mode) the target.
HOME is a temp dir; nothing real (~/.ssh, an agent, a server, the docker socket) is touched.

Red twins: the same probe under the closed profile is denied the ssh key, the agent, the variable
and the outside write - so the open rows are not vacuous - and both keep the core."""
from __future__ import annotations

import json
import os
import re
import socket

import pytest

from tests.factory.conftest import HARNESSES, logs, make_fws, run, sealed_job
from tests.holdout.conftest import needs_jail

PROBE = r'''
import json, os, pathlib, stat
ws = pathlib.Path(os.environ["KONSTANT_HOME"])
home = pathlib.Path(os.environ["HOME"])
out = {}

def read(key, p):
    try:
        out[key] = "READ" if pathlib.Path(p).read_text().strip() else "EMPTY"
    except OSError as exc:
        out[key] = type(exc).__name__

def write(key, p, append=False):
    p = pathlib.Path(p)
    try:
        if append:
            os.close(os.open(p, os.O_WRONLY | os.O_APPEND))   # opened for writing, nothing written
        else:
            p.write_text("planted\n")
            p.unlink()
        out[key] = "WROTE"
    except OSError as exc:
        out[key] = type(exc).__name__

read("ssh_key", home / ".ssh" / "id_planted")
read("token_file", os.environ["PROBE_TOKEN_FILE"])
write("outside", pathlib.Path(os.environ["PROBE_OUTSIDE"]) / f"w-{os.getpid()}")
sock = os.environ.get("SSH_AUTH_SOCK", "")
try:
    out["ssh_agent"] = "SOCKET" if sock and stat.S_ISSOCK(os.stat(sock).st_mode) else "none"
except OSError as exc:
    out["ssh_agent"] = type(exc).__name__
out["cred_var"] = "SET" if os.environ.get("GITHUB_TOKEN") else "unset"
store = ws / "var" / "holdout"
try:
    found = [str(p) for p in store.rglob("*") if p.is_file()]
    out["holdout"] = "READ" if any(pathlib.Path(f).read_text() for f in found) else "masked"
except OSError as exc:
    out["holdout"] = type(exc).__name__
out["tokens"] = sorted(t.name for t in (ws / "var" / "secrets").glob("*.token")
                       if t.read_text().strip()) if (ws / "var" / "secrets").is_dir() else []
write("machinery_catalog", ws / "catalog" / f"planted-{os.getpid()}")
write("machinery_toml", ws / "konstant.toml", append=True)
write("machinery_db", ws / "var" / "board.db", append=True)
write("machinery_git", ws / "projects" / "greeter" / ".git" / "config", append=True)
write("target", ws / "projects" / "greeter" / f"planted-{os.getpid()}")
print("confine-probe: " + json.dumps(out, sort_keys=True), flush=True)
'''
CORE_TOKENS = ["viewer.token", "worker.token"]


def set_profile(w, profile: str, extra: str = "") -> None:
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + f'[confinement]\nprofile = "{profile}"\n{extra}')
    w.ok("agents", "sync")


@pytest.fixture()
def pws(tmp_path):
    """The factory workspace (tests/factory/conftest.py) plus the planted host: ~/.ssh key, a
    token file outside the workspace, an outside dir, and a listening ssh-agent stand-in."""
    w = make_fws(tmp_path)
    srv = None
    try:
        (w.fake_home / ".config").mkdir(exist_ok=True)
        tok = w.fake_home / "service.token"
        tok.write_text("PLANTED-SERVICE-TOKEN\n")
        outside = tmp_path / "outside"
        outside.mkdir()
        sock = tmp_path / "agent.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock))
        srv.listen(1)
        probe = w.src / "confine_probe.py"
        probe.write_text(PROBE)
        (w.src / "sitecustomize.py").write_text(       # only in a phase process
            "import os, runpy, sys\n"
            "a = ' '.join(sys.argv)\n"
            "if os.environ.get('KONSTANT_IN_TASK') == '1' and '--dump-config' not in a and any(\n"
            "        s in a for s in ('fake_harness.py', 'stub_cli.py', 'stub_dsh.py')):\n"
            f"    runpy.run_path({str(probe)!r})\n")
        w.probe_env = dict(PYTHONPATH=f"{w.src}:{os.environ.get('PYTHONPATH', '')}",
                           PROBE_OUTSIDE=str(outside), PROBE_TOKEN_FILE=str(tok),
                           SSH_AUTH_SOCK=str(sock), GITHUB_TOKEN="planted-gh-token")
        w.outside = outside
        yield w
    finally:
        if srv is not None:
            srv.close()
        w.stop_board()


def probes(rd) -> list:
    seen = [json.loads(m) for m in re.findall(r"^confine-probe: (.*)$", logs(rd), re.M)]
    assert seen, logs(rd)[-3000:]
    return seen


def assert_core(s: dict, factory: bool) -> None:
    """The integrity core: no profile opens it."""
    assert s["holdout"] != "READ", s
    assert s["tokens"] == CORE_TOKENS, s
    for k in ("machinery_catalog", "machinery_toml", "machinery_db", "machinery_git"):
        assert s[k] != "WROTE", (k, s)
    if factory:
        assert s["target"] != "WROTE", s


@needs_jail
@pytest.mark.parametrize("harness", HARNESSES)
def test_open_factory_phase_reaches_the_host_but_not_the_core(pws, harness):
    set_profile(pws, "open")
    jid = sealed_job(pws)
    res, rd = run(pws, harness, jid, **pws.probe_env)
    for s in probes(rd):
        assert s["ssh_key"] == "READ" and s["token_file"] == "READ", s     # the host, as open
        assert s["outside"] == "WROTE" and s["ssh_agent"] == "SOCKET", s
        assert s["cred_var"] == "SET", s
        assert_core(s, factory=True)
    assert res.returncode == 0, res.stderr[-3000:]
    assert pws.json("job", "show", jid)["status"] == "verified"
    assert not list(pws.outside.iterdir())                    # the probe removed what it wrote


@needs_jail
@pytest.mark.parametrize("harness", HARNESSES)
def test_open_level4_phase_is_jailed_thin_and_keeps_the_core(pws, harness):
    """Level 4 (no holdouts): the open profile wraps EVERY harness in the thin jail, because the
    jail is what keeps the integrity core around a phase that otherwise has the host."""
    set_profile(pws, "open")
    jid = pws.add_job()
    res, rd = run(pws, harness, jid, **pws.probe_env)
    for s in probes(rd):
        assert s["ssh_key"] == "READ" and s["outside"] == "WROTE", s
        assert s["ssh_agent"] == "SOCKET" and s["cred_var"] == "SET", s
        assert_core(s, factory=False)
    assert res.returncode == 0, res.stderr[-3000:]


@needs_jail
@pytest.mark.parametrize("harness", HARNESSES)
def test_closed_factory_phase_red_twin_no_host_and_the_core(pws, harness):
    """The same probe under closed (the default): the host reach the open rows assert is denied,
    so those rows are not vacuous; the core holds the same way."""
    jid = sealed_job(pws)
    res, rd = run(pws, harness, jid, **pws.probe_env)
    for s in probes(rd):
        assert s["ssh_key"] != "READ" and s["outside"] != "WROTE", s
        assert s["ssh_agent"] != "SOCKET" and s["cred_var"] == "unset", s
        assert s["token_file"] == "READ", s      # documented: other files in your home stay
        assert_core(s, factory=True)
    assert res.returncode == 0, res.stderr[-3000:]


@needs_jail
def test_integrity_off_refuses_factory_mode_red(pws):
    """integrity = "off" is level 4 only: a job with sealed holdouts refuses to start (exit 2)
    and no phase runs."""
    jid = sealed_job(pws)
    set_profile(pws, "open", 'integrity = "off"\n')
    res, rd = run(pws, "command", jid, **pws.probe_env)
    assert res.returncode == 2, res.stderr[-2000:]
    assert 'holdouts need a confined phase: [confinement] integrity = "off"' in res.stderr
    assert rd is None or not list(rd.glob("phases/*.log"))
    assert pws.json("job", "show", jid)["status"] == "queued"


@needs_jail
def test_integrity_off_level4_red_twin_the_core_is_really_gone(pws):
    """With the core off (open, level 4) the same probe reads every token and writes machinery:
    what the green rows assert is the integrity core's doing, not an accident."""
    set_profile(pws, "open", 'integrity = "off"\n')
    res, rd = run(pws, "command", pws.add_job(), **pws.probe_env)
    s = probes(rd)[0]
    assert "owner.token" in s["tokens"] and "verifier.token" in s["tokens"], s
    assert s["machinery_catalog"] == "WROTE" and s["machinery_toml"] == "WROTE", s
    res = pws.run("--json", "doctor", env=pws.henv())       # the stub dsh first on PATH
    doc = {r["check"]: r for r in json.loads(res.stdout)["checks"]}
    assert doc["integrity core"]["status"] == "FAIL"
