"""Each adapter maps the confinement profile and options faithfully (konstant/confinement.py,
wave L5-2b), and every one of them keeps the integrity core under the open profile: Claude Code's
settings, the codex permission profile, the gemini policy, the dsh patches and konstant's jail.
The closed profile renders exactly what 0.1.0 rendered (conf=None). Red twins: with the integrity
core turned off (open, level 4) the core's rules are gone - so the green rows test the rules, not
an accident of the rendering."""
from __future__ import annotations

import json
import os
import re

import pytest

from konstant import jail, machinery
from konstant.agents import settings
from konstant.confinement import CLOSED, parse
from konstant.harnesses import codex, dsh, dsh_session, gemini
from konstant.harnesses.base import Phase, jail_layout
from tests.harness.conftest import values

OPEN = parse({"profile": "open"})
OFF = parse({"profile": "open", "integrity": "off"})


def phase(ws, conf, identity="worker", factory=False):
    return Phase({**values(ws), "out": ws / "var/runs/r1/out"}, wconf=conf, identity=identity,
                 factory=factory)


def test_closed_renders_exactly_the_010_surfaces(ws, home):
    assert settings.render(ws, {}, conf=CLOSED) == settings.render(ws, {})
    assert gemini.policy(ws, [], "h", CLOSED) == gemini.policy(ws, [], "h")
    assert dsh.patch(ws, {}, "h", CLOSED) == dsh.patch(ws, {}, "h")
    assert dsh_session.session_patch(ws, {}, {}, "h", CLOSED) == \
        dsh_session.session_patch(ws, {}, {}, "h")
    assert codex.filesystem(phase(ws, CLOSED)) == codex.filesystem(Phase(
        {**values(ws), "out": ws / "var/runs/r1/out"}))


def claude_core(data, ws) -> list:
    """The integrity-core rules missing from a rendered Claude settings file."""
    deny = data["permissions"]["deny"]
    w = settings.abs_rule(ws)
    want = [f"Read({w}/var/secrets/**)"] + [f"Read({w}/{d}/**)" for d in machinery.SEALED]
    want += [f"Edit({w}/{d}/**)" for d in machinery.DIRS] + \
        [f"Edit({w}/{f})" for f in machinery.FILES]
    missing = [r for r in want if r not in deny]
    fs = data["sandbox"]["filesystem"]
    missing += [p for p in (str(ws / "var/secrets"), *map(str, machinery.sealed(ws)))
                if p not in fs["denyRead"]]
    missing += [p for p in (*machinery.DIRS, *machinery.FILES)
                if str(ws / p) not in fs["denyWrite"]]
    return missing


def test_claude_open_opens_the_host_and_keeps_the_core_green(ws, home):
    data = json.loads(settings.render(ws, {}, conf=OPEN))
    assert claude_core(data, ws) == []
    allow = data["permissions"]["allow"]
    assert {"Bash", "Read(//**)", "Edit(//**)"} <= set(allow)
    assert data["permissions"]["blockReadsOutsideWorkingDirectories"] is False
    fs = data["sandbox"]["filesystem"]
    assert "/" in fs["allowWrite"] and "~/.ssh" not in fs["denyRead"]
    net = data["sandbox"]["network"]
    assert net["allowedDomains"] == ["*"] and net["allowAllUnixSockets"] is True


def test_claude_integrity_off_red_twin_drops_the_core(ws, home):
    assert len(claude_core(json.loads(settings.render(ws, {}, conf=OFF)), ws)) > 10


def test_claude_options_map_one_by_one(ws, home):
    c = parse({"home_write": True, "extra_read": ["/opt/data"], "extra_write": ["/opt/out"],
               "credentials": ["~/.ssh"], "network": False, "docker_socket": True,
               "home_read": False})
    data = json.loads(settings.render(ws, {}, conf=c))
    p, fs = data["permissions"], data["sandbox"]["filesystem"]
    assert "Edit(~/**)" in p["allow"] and "Edit(//opt/out/**)" in p["allow"]
    assert "Read(//opt/data/**)" in p["allow"] and "//opt/data" in p["additionalDirectories"]
    assert "~/" in fs["allowWrite"] and "/opt/out" in fs["allowWrite"]
    assert "~/.ssh" not in fs["denyRead"] and "~/.aws" in fs["denyRead"]
    assert "~/" in fs["denyRead"] and str(ws) in fs["allowRead"]
    assert data["sandbox"]["network"] == {"allowedDomains": [],
                                          "allowUnixSockets": list(machinery.DOCKER_SOCKETS)}
    assert claude_core(data, ws) == [] and "Bash" not in p["allow"]


def test_codex_open_profile_keeps_the_core_green_and_off_red(ws, home):
    (home / ".ssh").mkdir()
    (ws / "var" / "holdout").mkdir()
    fs = codex.filesystem(phase(ws, OPEN))
    assert fs[":root"] == "write" and "~/.ssh" not in fs
    assert fs[f"{ws / 'var/holdout'}/**"] == "deny"
    assert fs[f"{ws / 'var'}/**"] == "read" and fs[f"{ws / 'catalog'}/**"] == "read"
    for t in ("owner.token", "orchestrator.token", "verifier.token"):
        assert fs[str(ws / "var/secrets" / t)] == "deny"
    off = codex.filesystem(phase(ws, OFF))
    assert f"{ws / 'var/holdout'}/**" not in off and f"{ws / 'catalog'}/**" not in off
    closed = codex.filesystem(phase(ws, CLOSED))
    assert closed[":root"] == "read" and closed["~/.ssh"] == "deny"


def test_codex_network_option(ws, home):
    argv = codex.Codex().argv(phase(ws, parse({"network": False})))
    assert "permissions.konstant.network.enabled=false" in argv
    assert "permissions.konstant.network.enabled=true" in codex.Codex().argv(phase(ws, OPEN))


def deny_rx(pol: str):
    pattern = re.search(r'argsPattern = "(.*)"\ndecision = "deny"', pol)
    return re.compile(json.loads(f'"{pattern.group(1)}"')) if pattern else None


def test_gemini_open_allows_any_command_and_keeps_the_core(ws, home):
    pol = gemini.policy(ws, [], "h", OPEN)
    assert 'toolName = "run_shell_command"\ndecision = "allow"\npriority = 50' in pol
    rx = deny_rx(pol)
    for p in (*machinery.DIRS, *machinery.FILES):
        probe = f'"file_path":"{ws / p}' + ("/x" if p in machinery.DIRS else '"')
        assert rx.search(probe), p
    assert "read_file" in pol and "var/holdout" in pol
    assert deny_rx(gemini.policy(ws, [], "h", OFF)) is None             # red twin
    argv = gemini.Gemini().argv(phase(ws, parse({"extra_read": ["/opt/data"]})))
    assert argv[argv.index("/opt/data") - 1] == "--include-directories"


def test_dsh_open_patch_full_access_session_stays_workspace_write(ws, home):
    assert "    mode: danger-full-access" in dsh.patch(ws, {}, "h", OPEN)
    assert "    mode: workspace-write" in dsh.patch(ws, {}, "h", CLOSED)
    sess = dsh_session.session_patch(ws, {}, {}, "h", OPEN)
    assert "    mode: workspace-write" in sess and "danger-full-access" not in sess
    env = dsh.Dsh().env(phase(ws, OPEN))
    assert env["DSH_PERMISSION_MODE"] == "danger-full-access"
    assert dsh.Dsh().env(phase(ws, CLOSED))["DSH_PERMISSION_MODE"] == "workspace-write"


def effective(argv, path: str) -> str:
    """What bwrap's mount list makes of `path`: the LAST mount over it or an ancestor wins
    (a later mount on an ancestor hides an earlier one below it)."""
    kinds = {"--bind": "rw", "--ro-bind": "ro", "--tmpfs": "masked", "--dev": "dev",
             "--proc": "proc"}
    last = None
    i = 1
    while i < len(argv) and argv[i] != "--":
        a = argv[i]
        if a in ("--bind", "--ro-bind"):
            dest = argv[i + 2]
            i += 3
        elif a in ("--tmpfs", "--dev", "--proc", "--chdir"):
            dest = argv[i + 1]
            i += 2
        else:
            i += 1
            continue
        if a in kinds and (path == dest or path.startswith(dest.rstrip("/") + "/")):
            last = "masked" if a == "--ro-bind" and argv[i - 2] == os.devnull else kinds[a]
    return last


@pytest.mark.skipif(not jail.available(), reason="bubblewrap cannot run here")
@pytest.mark.parametrize("conf", [CLOSED, OPEN], ids=["closed", "open"])
def test_jail_keeps_every_machinery_path_read_only_and_masks_the_core(ws, home, conf):
    (ws / "var" / "holdout").mkdir()
    (home / ".ssh").mkdir()
    for d in machinery.DIRS:
        (ws / d).mkdir(parents=True, exist_ok=True)
    for f in machinery.FILES:
        (ws / f).touch()
    ph = phase(ws, conf, factory=True)
    lay = jail_layout(ph)
    argv = jail.wrap(["true"], **lay)
    assert argv[1] == ("--bind" if conf.open else "--ro-bind") and argv[2:4] == ["/", "/"]
    for p in (*machinery.DIRS, *machinery.FILES):
        if not p.startswith(("var/secrets", "var/holdout")):
            assert effective(argv, os.path.realpath(ws / p)) == "ro", p
    assert effective(argv, os.path.realpath(ws / "projects" / "demo" / "x")) == "rw"  # its clone
    assert effective(argv, os.path.realpath(ws / "projects" / "other")) == "ro"  # target, clones
    assert effective(argv, str(ws / "var/secrets/owner.token")) == "masked"
    assert effective(argv, str(ws / "var/secrets/worker.token")) == "ro"
    assert effective(argv, str(ws / "var/holdout/2/H1.scenario")) == "masked"
    assert effective(argv, str(home / ".ssh" / "id")) == ("rw" if conf.open else "masked")
    assert effective(argv, str(home.parent / "outside")) == ("rw" if conf.open else "ro")


def test_scenario_writer_phase_is_closed_under_open(ws, home):
    ph = phase(ws, OPEN, identity="scenario", factory=True)
    assert ph.conf == CLOSED and jail_layout(ph)["root_rw"] is False
