"""Unit level of factory confinement and identities (docs/LEVEL5.md 2.1, 2.2, wave L5-2): the
jailed argv of each adapter, the identity token exposure, relocatable homes, the codex profile's
token denials, Claude Code's sandbox fallback, the in-task client and fail-closed starts."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from konstant import harnesses, jail, machinery
from konstant.board.policy import PHASE_IDENTITIES
from konstant.harnesses import claude as claude_mod
from konstant.harnesses import codex as codex_mod
from konstant.harnesses.base import HarnessError, Phase
from tests.holdout.conftest import needs_jail


@pytest.fixture()
def ws(tmp_path):
    w = tmp_path / "ws"
    for d in ("var/secrets", "var/holdout/2", "var/runs/r1", "projects/demo", ".claude"):
        (w / d).mkdir(parents=True)
    for t in machinery.ALL_TOKENS:
        (w / "var" / "secrets" / t).write_text("t\n")
    (w / ".claude" / "settings.json").write_text(json.dumps(
        {"permissions": {"allow": []}, "sandbox": {"enabled": True}}))
    return w


def phase(ws, factory=True, identity="worker", jail_on=True) -> Phase:
    return Phase({"workspace": ws, "cwd": ws / "projects" / "demo", "run_dir": ws / "var/runs/r1",
                  "prompt": "p", "prompt_file": ws / "var/runs/r1/prompts/01-x.md", "agent": "coder",
                  "out": ws / "projects/demo/.audits/x/out"},
                 factory=factory, identity=identity, jail=jail_on)


def adapter(name):
    return harnesses.Choice(name, "", "tool {prompt_file}" if name == "command" else None,
                            False, "[harness]").adapter


def exposed(argv) -> list:
    return [argv[i + 1] for i, a in enumerate(argv[:-2]) if a == "--ro-bind"
            and argv[i + 1] == argv[i + 2] and argv[i + 1].endswith(".token")]


NAMES = ("claude", "codex", "gemini", "dsh", "command")


@needs_jail
@pytest.mark.parametrize("name", NAMES)
def test_factory_phase_is_jailed_on_every_adapter_green(ws, name):
    ad = adapter(name)
    ph = phase(ws)
    ad.prepare(ph)
    try:
        argv = ad.confine(["tool"], ph)
        assert argv[0].endswith("bwrap") and argv[-1] == "tool", argv
        store = str((ws / "var" / "holdout").resolve())
        assert any(argv[i] == "--tmpfs" and argv[i + 1] == store for i in range(len(argv) - 1))
        sec = str((ws / "var" / "secrets").resolve())
        assert sorted(exposed(argv)) == [f"{sec}/viewer.token", f"{sec}/worker.token"]
        assert ad.confines(True, True)
    finally:
        ad.cleanup(ph)


@needs_jail
@pytest.mark.parametrize("name", ("claude", "codex", "gemini", "command"))
def test_outside_factory_mode_the_argv_is_unchanged_red_twin(ws, name):
    """Level 4 is unchanged: without factory mode these adapters do not jail the phase (so the
    green test above shows what factory mode adds); dsh jails every phase either way."""
    ad = adapter(name)
    ph = phase(ws, factory=False)
    assert ad.confine(["tool"], ph) == ["tool"] and not ad.confines(True, False)
    assert adapter("dsh").confines(True, False)


@needs_jail
@pytest.mark.parametrize("identity", PHASE_IDENTITIES)
def test_a_phase_reads_only_its_own_identity_token(ws, identity):
    argv = adapter("command").confine(["tool"], phase(ws, identity=identity))
    sec = str((ws / "var" / "secrets").resolve())
    assert sorted(exposed(argv)) == sorted([f"{sec}/{identity}.token", f"{sec}/viewer.token"])
    assert machinery.tokens_denied(identity) == tuple(
        t for t in machinery.ALL_TOKENS if t not in (f"{identity}.token", "viewer.token"))


def test_an_unknown_identity_is_refused(ws):
    with pytest.raises(ValueError):
        machinery.tokens_readable("owner")
    from konstant.gate.harness import Harness
    h = Harness("tool {prompt_file}", workspace=ws, factory=True)
    with pytest.raises(HarnessError, match="a phase acts as one of"):
        h.run("p", agent="coder", cwd=ws, run_dir=ws / "var/runs/r1", label="x",
              identity="factory")


def test_factory_phase_never_starts_unjailed(ws, monkeypatch):
    """Fail closed (LEVEL5 1, 2.1): with the jail unavailable a factory phase refuses to start
    instead of running unconfined; the same harness outside factory mode still starts."""
    from konstant.gate.harness import Harness
    monkeypatch.setattr(jail, "available", lambda: False)
    h = Harness("true {prompt_file}", workspace=ws, factory=True)
    with pytest.raises(HarnessError, match="holdouts need a confined phase"):
        h.run("p", agent="coder", cwd=ws, run_dir=ws / "var/runs/r1", label="x")
    ok = Harness("true {prompt_file}", workspace=ws).run("p", agent="coder", cwd=ws,
                                                         run_dir=ws / "var/runs/r1", label="y")
    assert ok.rc == 0


def test_relocatable_home_per_adapter():
    got = {n: harnesses.adapter(n).relocatable_home for n in NAMES}
    assert got == {"claude": True, "codex": True, "gemini": True, "dsh": True, "command": False}


def test_codex_profile_denies_the_other_identities_tokens(ws):
    fs = codex_mod.filesystem(phase(ws))
    sec = ws / "var" / "secrets"
    for t in ("owner", "orchestrator", "verifier", "planner", "dod-reviewer", "scenario",
              "factory"):
        assert fs[str(sec / f"{t}.token")] == "deny", t
    assert str(sec / "worker.token") not in fs and str(sec / "viewer.token") not in fs
    fs = codex_mod.filesystem(phase(ws, identity="scenario"))
    assert fs[str(sec / "worker.token")] == "deny" and str(sec / "scenario.token") not in fs


@needs_jail
def test_claude_factory_phase_relocates_its_home_and_binds_only_the_credential(ws, tmp_path,
                                                                               monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    ad, ph = adapter("claude"), phase(ws)
    ad.prepare(ph)
    try:
        env = ad.env(ph)
        cfg_dir = Path(env["CLAUDE_CONFIG_DIR"])
        assert cfg_dir.is_dir() and "/var/harness/claude/phases/" in str(cfg_dir)
        argv = ad.confine(["claude", "--settings", str(ws / ".claude/settings.json")], ph)
        i = argv.index(str((home / ".claude" / ".credentials.json").resolve()))
        assert argv[i - 1] == "--ro-bind" and argv[i + 1] == str(cfg_dir / ".credentials.json")
    finally:
        ad.cleanup(ph)
    assert not cfg_dir.exists()


@needs_jail
def test_claude_sandbox_fallback_when_it_cannot_nest(ws, monkeypatch):
    """LEVEL5 2.1: when Claude Code's sandbox cannot run inside the jail the factory phase gets
    the same settings minus `sandbox` (the jail is the boundary); when it can, they are kept."""
    settings = str(ws / ".claude/settings.json")
    ad, ph = adapter("claude"), phase(ws)
    ad.prepare(ph)
    try:
        monkeypatch.setattr(claude_mod, "sandbox_nests", lambda *a: False)
        argv = ad.confine(["claude", "--settings", settings, "go"], ph)
        used = argv[argv.index("--settings") + 1]
        assert used != settings and "sandbox" not in json.loads(Path(used).read_text())
        monkeypatch.setattr(claude_mod, "sandbox_nests", lambda *a: True)
        argv = ad.confine(["claude", "--settings", settings, "go"], ph)
        assert argv[argv.index("--settings") + 1] == settings
    finally:
        ad.cleanup(ph)


def test_in_task_client_uses_the_phase_identity_token(ws, monkeypatch):
    from konstant import client
    from konstant.config import Config
    for label in ("worker", "scenario", "viewer"):
        (ws / "var" / "secrets" / f"{label}.token").write_text(f"{label}-value\n")
    cfg = Config(home=ws)
    monkeypatch.setenv("KONSTANT_IN_TASK", "1")
    monkeypatch.setenv("KONSTANT_IDENTITY", "scenario")
    assert client.token_for(cfg, "worker") == "scenario-value"
    assert client.token_for(cfg, "scenario") == "scenario-value"
    assert client.token_for(cfg, "viewer") == "viewer-value"
    for other in ("owner", "orchestrator", "planner", "factory"):
        with pytest.raises(client.ClientError, match="not available inside a task run"):
            client.token_for(cfg, other)
    monkeypatch.setenv("KONSTANT_IDENTITY", "owner")             # not a phase identity
    assert client.token_for(cfg, "worker") == "worker-value"
    monkeypatch.delenv("KONSTANT_IN_TASK")
    assert client.token_for(cfg, "scenario") == "scenario-value"  # outside a task: --as label


def test_jail_nests_reports_a_nested_sandbox():
    if not jail.available():
        assert jail.nests() is False
    else:
        assert isinstance(jail.nests(), bool)


def test_doctor_factory_rows(ws, monkeypatch):
    from konstant.config import Config
    from konstant.factory import doctor
    for t in machinery.ALL_TOKENS:
        os.chmod(ws / "var" / "secrets" / t, 0o600)
    cfg = Config(home=ws)
    cfg.data["harness"]["types"] = {"review": {"name": "command", "command": "t {prompt}"}}
    rows = {r[1]: r for r in doctor.rows(cfg)}
    assert set(rows) == {"factory jail", "factory harness", "claude sandbox", "identities"}
    assert rows["identities"][0] == "PASS"
    assert "command cannot relocate its home" in rows["factory harness"][2]
    os.remove(ws / "var" / "secrets" / "scenario.token")
    assert doctor.rows(cfg)[-1][0] == "WARN"
    cfg.data["gate"]["jail"] = False
    assert doctor.rows(cfg)[0][:2] == ("WARN", "factory jail")
