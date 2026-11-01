"""[confinement] (konstant/confinement.py, wave L5-2b): the two profiles, the per-capability options
that override them, the integrity core no option opens, and the fail-closed config check."""
from __future__ import annotations

from pathlib import Path

import pytest

from konstant import config, confinement, machinery
from konstant.confinement import CLOSED, ConfinementError, parse

DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_closed_is_the_default_and_the_010_reach():
    c = parse({})
    assert c == CLOSED and c.profile == "closed" and c.integrity
    assert (c.network, c.home_read, c.home_write, c.host_write) == (None, True, False, False)
    assert (c.credentials, c.ssh_agent, c.docker_socket, c.host_agents) == ((), False, False,
                                                                             False)
    assert not c.jails_level4() and not c.writes_outside


def test_open_profile_defaults():
    c = parse({"profile": "open"})
    assert c.open and c.integrity and c.jails_level4() and c.writes_outside
    assert (c.network, c.home_write, c.host_write, c.ssh_agent, c.docker_socket) == \
        (True, True, True, True, True)
    assert c.credentials == ("*",) and c.host_agents is False      # host_agents: own opt-in
    assert c.masked_credentials() == [] and c.env_drop() == []


def test_an_option_overrides_the_profile():
    c = parse({"profile": "open", "docker_socket": False, "credentials": ["~/.ssh"]})
    assert c.docker_socket is False and c.source("docker_socket") == "option"
    assert c.source("ssh_agent") == "profile open"
    c2 = parse({"home_write": True, "credentials": ["~/.ssh", "$GITHUB_TOKEN"]})
    assert c2.profile == "closed" and c2.home_write and c2.writes_outside
    assert "GITHUB_TOKEN" not in c2.env_drop() and "AWS_SECRET_ACCESS_KEY" in c2.env_drop()


def test_host_write_implies_home_write():
    assert parse({"host_write": True}).home_write


def test_closed_drops_credential_variables_and_sockets(monkeypatch):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/run/user/1/agent.sock")
    c = parse({})
    drop = c.env_drop()
    assert {"GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "SSH_AUTH_SOCK", "DOCKER_HOST"} <= set(drop)
    masked = c.sockets_masked()
    assert "/run/user/1/agent.sock" in masked and "/var/run/docker.sock" in masked
    assert parse({"ssh_agent": True, "docker_socket": True}).sockets_masked() == []


def test_credentials_pass_named_locations_only(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = parse({"credentials": ["~/.ssh"]})
    masked = c.masked_credentials()
    assert str(tmp_path / ".ssh") not in masked and str(tmp_path / ".aws") in masked
    assert len(CLOSED.masked_credentials()) == len(machinery.CREDENTIALS)


def test_the_scenario_writer_always_runs_closed_and_factory_never_gets_docker():
    c = parse({"profile": "open"})
    assert c.for_phase("scenario") == CLOSED
    f = c.for_phase("worker", factory=True)
    assert f.docker_socket is False and f.integrity and f.ssh_agent and f.host_write
    off = parse({"profile": "open", "integrity": "off"})
    assert not off.integrity and off.for_phase("worker", factory=True).integrity


@pytest.mark.parametrize("raw,needle", [
    ({"profile": "ajar"}, "profile = 'ajar'"),
    ({"integrity": "maybe"}, "integrity"),
    ({"integrity": "off"}, "needs profile = \"open\""),
    ({"netwrok": True}, "unknown key 'netwrok'"),
    ({"network": "yes"}, "network must be true or false"),
    ({"extra_read": "/opt"}, "extra_read must be a list"),
    ({"extra_write": ["relative/dir"]}, "absolute path"),
    ({"extra_write": ["/opt/../etc"]}, "no '..'"),
    ({"credentials": ["$not ok"]}, "not a $VARIABLE"),
])
def test_malformed_confinement_refused_red(raw, needle):
    with pytest.raises(ConfinementError, match=__import__("re").escape(needle)):
        parse(raw)


@pytest.mark.parametrize("key,rel", [
    ("extra_write", "catalog"), ("extra_write", "var/board.db"), ("extra_write", ".claude"),
    ("extra_write", "var/runs"), ("extra_read", "var/secrets"), ("extra_read", "var/holdout/2"),
    ("credentials", "var/secrets/owner.token"),
])
def test_no_option_reaches_into_the_integrity_core_red(tmp_path, key, rel):
    with pytest.raises(ConfinementError, match="integrity core"):
        parse({key: [str(tmp_path / rel)]}, tmp_path)


def test_options_outside_the_core_accepted_green(tmp_path):
    c = parse({"extra_write": [str(tmp_path.parent / "elsewhere")],
               "extra_read": [str(tmp_path / "projects")], "credentials": ["~/.ssh"]}, tmp_path)
    assert c.extra_write and c.extra_read and c.credentials == ("~/.ssh",)


def test_config_loads_and_refuses_confinement(tmp_path):
    (tmp_path / "konstant.toml").write_text('[confinement]\nprofile = "open"\n')
    assert config.load(tmp_path).confinement().open
    (tmp_path / "konstant.toml").write_text('[confinement]\nintegrity = "off"\n')
    with pytest.raises(config.ConfigError, match=r"\[confinement\] integrity"):
        config.load(tmp_path)
    (tmp_path / "konstant.toml").write_text('[confinement]\nextra_write = ["%s"]\n'
                                            % (tmp_path / "var"))
    with pytest.raises(config.ConfigError, match="integrity core"):
        config.load(tmp_path)


def test_every_option_is_documented_with_what_it_allows_and_risks():
    """docs/CONCEPTS.md carries the options table; DESIGN §13 names every key."""
    concepts = (DOCS / "CONCEPTS.md").read_text()
    design = (DOCS / "DESIGN.md").read_text()
    for k in confinement.OPTIONS:
        assert f"| `{k}` |" in concepts, k
        assert k in design, k
    assert "protects the meaning of \"verified\", not the host" in concepts
