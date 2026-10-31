"""`konstant doctor` per harness: detection on PATH (with version), one reach row per configured
harness naming what it cannot enforce, and the dsh layer check (a foreign layer = FAIL)."""
from __future__ import annotations

import json
import os
import sys

import pytest

from tests.cli.conftest import Workspace
from tests.fixtures import stub_dsh


def checks(res) -> dict:
    return {r["check"]: r for r in json.loads(res.stdout)["checks"]}


@pytest.fixture()
def fakebin(tmp_path):
    d = tmp_path / "fakebin"
    d.mkdir()
    return d


def tool(d, name, body):
    p = d / name
    p.write_text(f"#!{sys.executable}\n{body}\n")
    p.chmod(0o755)


def workspace(tmp_path, toml: str) -> Workspace:
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    (w.home / "konstant.toml").write_text((w.home / "konstant.toml").read_text() + toml)
    w.ok("board", "init")
    w.ok("agents", "sync")
    return w


def doctor(w, fakebin, home):
    env = w.env(PATH=f"{fakebin}:/usr/bin:/bin", HOME=str(home))
    return w.run("--json", "doctor", env=env)


def test_named_harness_found_with_version_and_overrides_listed(tmp_path, fakebin, home):
    tool(fakebin, "codex", "print('codex-cli 9.9.9')")
    w = workspace(tmp_path, '[harness]\nname = "codex"\nmodel = "m1"\n'
                            '[harness.types.review]\nname = "gemini"\n')
    res = doctor(w, fakebin, home)
    c = checks(res)
    assert res.returncode == 0, res.stdout
    assert c["harness"]["status"] == "PASS" and "codex-cli 9.9.9" in c["harness"]["detail"]
    assert "codex model m1" in c["harness"]["detail"]
    assert c["harness review"]["status"] == "WARN" and "not found" in c["harness review"]["detail"]
    assert c["reach"]["status"] == "WARN" and "COMMANDS:" in c["reach"]["detail"]
    assert c["reach gemini"]["status"] == "WARN"


def test_codex_user_level_leak_is_named_only_when_present(tmp_path, fakebin, home):
    tool(fakebin, "codex", "print('codex-cli 1')")
    w = workspace(tmp_path, '[harness]\nname = "codex"\n')
    assert "USER-LEVEL" not in checks(doctor(w, fakebin, home))["reach"]["detail"]
    (home / ".codex").mkdir()
    (home / ".codex" / "AGENTS.md").write_text("be helpful\n")
    detail = checks(doctor(w, fakebin, home))["reach"]["detail"]
    assert "USER-LEVEL" in detail and ".codex/AGENTS.md" in detail


def test_claude_reach_names_user_memory(tmp_path, fakebin, home):
    tool(fakebin, "claude", "print('2.1.0 (Claude Code)')")
    w = workspace(tmp_path, "")
    (home / ".claude").mkdir()
    (home / ".claude" / "CLAUDE.md").write_text("x\n")
    c = checks(doctor(w, fakebin, home))
    assert "CLAUDE.md" in c["reach"]["detail"] and "loads into every phase" in c["reach"]["detail"]


def test_command_adapter_reach_is_unknown(tmp_path, fakebin, home):
    w = workspace(tmp_path, f'[harness]\nname = "command"\ncommand = "{sys.executable} '
                            '-c pass {prompt_file}"\n')
    c = checks(doctor(w, fakebin, home))
    assert c["harness"]["status"] == "PASS"
    assert c["reach"]["status"] == "WARN" and "konstant cannot see" in c["reach"]["detail"]


def test_custom_command_under_a_named_adapter_is_info(tmp_path, fakebin, home):
    w = workspace(tmp_path, f'[harness]\ncommand = "{sys.executable} -c pass {{prompt}}"\n')
    c = checks(doctor(w, fakebin, home))
    assert c["reach"]["status"] == "INFO" and "cannot vouch" in c["reach"]["detail"]


def test_bad_override_type_fails_doctor(tmp_path, fakebin, home):
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    w.ok("board", "init")
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness.types.nosuch]\nname = "codex"\n')
    c = checks(doctor(w, fakebin, home))
    assert c["agents"]["status"] == "FAIL" and "not a task type" in c["agents"]["detail"]


@pytest.mark.parametrize("foreign", [True, False])
def test_dsh_layer_check_red_and_green(tmp_path, fakebin, home, foreign):
    """A launcher that forces its own DSH_HOME (a profile layer of the operator's) is a FAIL: no
    phase starts on that composition (fail closed; G-05)."""
    w = workspace(tmp_path, '[harness]\nname = "dsh"\n')
    stub_dsh.install(fakebin)
    env = w.env(PATH=f"{fakebin}:/usr/bin:/bin", HOME=str(home))
    if foreign:
        op = tmp_path / "operator-home"
        (op / "profiles" / "headless").mkdir(parents=True)
        (op / "profiles" / "headless" / "cordis.patch.yml").write_text(
            "- id: approval\n  config: {policy: ask}\n")
        env.update(STUB_DSH_DUMP="forced", STUB_DSH_FORCED_HOME=str(op))
    c = checks(w.run("--json", "doctor", env=env))
    if foreign:
        assert c["dsh layers"]["status"] == "FAIL", c["dsh layers"]
        assert str(op) in c["dsh layers"]["detail"] and "DSH_HOME ignored" in \
            c["dsh layers"]["detail"]
    else:
        assert c["dsh layers"]["status"] == "PASS", c["dsh layers"]
    assert c["reach"]["status"] == "WARN" and "COMMANDS:" in c["reach"]["detail"]


@pytest.mark.parametrize("jail_on", [True, False])
def test_dsh_reads_row_follows_the_jail(tmp_path, fakebin, home, jail_on):
    """The reads cell is `enforced` only while konstant's jail confines the dsh phase."""
    from konstant import jail
    w = workspace(tmp_path, '[harness]\nname = "dsh"\n' + ("" if jail_on else
                                                             "[gate]\njail = false\n"))
    stub_dsh.install(fakebin)
    detail = checks(doctor(w, fakebin, home))["reach"]["detail"]
    if jail_on and jail.available():
        assert "reads enforced" in detail and "READS:" not in detail, detail
    else:
        assert "READS: reads are not confined" in detail, detail


def test_dsh_under_tmp_is_warned(tmp_path, fakebin, home):
    w = workspace(tmp_path, '[harness]\nname = "dsh"\n')
    stub_dsh.install(fakebin)
    c = checks(doctor(w, fakebin, home))
    if os.path.realpath(str(w.home)).startswith("/tmp/"):
        assert c["dsh /tmp"]["status"] == "WARN"
    else:
        assert "dsh /tmp" not in c
