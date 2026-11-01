"""`konstant confinement show` and the doctor rows (wave L5-2b): the effective profile, each
option's value and source, and per configured harness how each capability is enforced at level 4
and in factory mode."""
from __future__ import annotations

import json

import pytest

from konstant import jail
from tests.cli.conftest import Workspace
from tests.fixtures import stub_dsh


class SafeWorkspace(Workspace):
    """Every command runs with tests/fixtures/stub_dsh.py first on PATH: doctor composes the dsh
    layers, and the host's own `dsh` (a launcher that may force the operator's personal home)
    must never be the one it runs."""

    def env(self, **extra) -> dict:
        bindir = self.home.parent / f"{self.home.name}-bin"
        if not (bindir / "dsh").exists():
            bindir.mkdir(exist_ok=True)
            stub_dsh.install(bindir)
        return super().env(**{"PATH": f"{bindir}:/usr/bin:/bin", **extra})


def ws(tmp_path, conf: str = "") -> Workspace:
    w = SafeWorkspace(tmp_path)
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n'
                    '[harness.types.review]\nname = "claude"\n' + conf)
    w.ok("board", "init")
    w.ok("agents", "sync")
    return w


def show(w) -> dict:
    return json.loads(w.ok("confinement", "show", "--json").stdout)


def test_show_closed_default(tmp_path):
    m = show(ws(tmp_path))
    assert m["profile"] == "closed" and m["integrity"] == "on"
    assert all(v["source"] == "profile closed" for v in m["options"].values())
    assert set(m["harnesses"]) == {"dsh", "claude"}
    claude = m["harnesses"]["claude"]
    assert claude["level4"]["jailed"] is False                    # Claude Code's own rules
    assert claude["level4"]["options"]["network"]["how"].startswith("Claude Code's sandbox")
    if jail.available():
        assert claude["factory"]["jailed"] is True and m["harnesses"]["dsh"]["level4"]["jailed"]
    for k in ("allows", "risks"):
        assert m["options"]["docker_socket"][k]


@pytest.mark.skipif(not jail.available(), reason="bubblewrap cannot run here")
def test_show_open_jails_every_harness_at_level4(tmp_path):
    m = show(ws(tmp_path, '[confinement]\nprofile = "open"\ndocker_socket = false\n'))
    assert m["profile"] == "open" and m["options"]["docker_socket"]["source"] == "option"
    for name, per in m["harnesses"].items():
        assert per["level4"]["jailed"] and per["factory"]["jailed"], name
        assert per["level4"]["options"]["integrity core"]["enforced"] == "enforced", name
        assert per["level4"]["options"]["host_write"]["how"] == "the host root bound writable"
    (tmp_path / "t").mkdir()
    out = ws(tmp_path / "t", '[confinement]\nprofile = "open"\n').ok("confinement",
                                                                      "show").stdout
    assert "confinement: profile open, integrity on" in out
    assert "docker_socket  true" in out and "partial" in out    # docker passed at level 4


def test_doctor_rows(tmp_path):
    rows = {r["check"]: r for r in json.loads(ws(tmp_path).run("--json", "doctor").stdout)
            ["checks"]}
    assert rows["integrity core"]["status"] == "PASS"
    assert rows["confinement"]["status"] == "PASS"
    (tmp_path / "o").mkdir()
    w = ws(tmp_path / "o", '[confinement]\nprofile = "open"\nintegrity = "off"\n')
    res = w.run("--json", "doctor")
    rows = {r["check"]: r for r in json.loads(res.stdout)["checks"]}
    assert res.returncode == 1 and rows["integrity core"]["status"] == "FAIL"
    assert "factory mode refuses to start" in rows["integrity core"]["detail"]
    assert rows["confinement"]["status"] == "WARN" and rows["docker socket"]["status"] == "WARN"


def test_doctor_warns_when_this_host_accepts_the_users_own_key(tmp_path):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_test.pub").write_text("ssh-ed25519 AAAAPLANTEDKEY test\n")
    (home / ".ssh" / "authorized_keys").write_text("ssh-ed25519 AAAAPLANTEDKEY test\n")
    (tmp_path / "w").mkdir()
    w = ws(tmp_path / "w", '[confinement]\nprofile = "open"\n')
    res = w.run("--json", "doctor", env=w.env(HOME=str(home)))
    rows = {r["check"]: r for r in json.loads(res.stdout)["checks"]}
    assert rows["dsh layers"]["status"] == "PASS", rows["dsh layers"]     # the stub, not the host's
    assert rows["ssh to this host"]["status"] == "WARN"
    assert "~/.ssh/id_test.pub" in rows["ssh to this host"]["detail"]
    (home / ".ssh" / "authorized_keys").write_text("ssh-ed25519 AAAAOTHER x\n")
    res = w.run("--json", "doctor", env=w.env(HOME=str(home)))
    assert "ssh to this host" not in {r["check"] for r in json.loads(res.stdout)["checks"]}
