"""Every adapter's command rendering against a golden file, and the resolution of [harness]
(default, per-type override, explicit template) - docs/HARNESSES.md."""
from __future__ import annotations

from pathlib import Path

import json
import shlex

import pytest

from konstant import catalog, harnesses
from konstant.config import ConfigError, check_harness
from konstant.gate.harness import Harness, HarnessError, HarnessSet
from tests.harness.conftest import golden, hcfg, norm, values

CAT = catalog.load()


def argv_of(ws, **over):
    return HarnessSet(hcfg(**over), ws, CAT).default.argv(values(ws))


@pytest.mark.parametrize("name,model", [("claude", ""), ("claude", "haiku"), ("codex", ""),
                                        ("codex", "gpt-5.4-mini"), ("gemini", "gemini-2.5-flash"),
                                        ("dsh", "local-model")])
def test_default_command_rendering_is_golden(ws, home, name, model):
    argv = argv_of(ws, name=name, model=model)
    text = "\n".join(norm(a, ws, home) for a in argv) + "\n"
    golden(f"argv-{name}{'-' + model if model else ''}.txt", text)


def test_codex_local_endpoint_adds_a_responses_provider(ws, home):
    argv = argv_of(ws, name="codex", model="served-name",
                   endpoint={"base_url": "http://127.0.0.1:8000/v1", "api_key_env": "LOCAL_KEY"})
    joined = shlex.join(argv)
    assert ('model_providers.konstant={"name"="konstant endpoint",'
            '"base_url"="http://127.0.0.1:8000/v1","wire_api"="responses","env_key"="LOCAL_KEY"}'
            ) in joined
    assert 'model_provider="konstant"' in argv and argv[-3:] == ["-m", "served-name", "-"]


def test_the_prompt_never_lands_in_argv_for_stdin_adapters(ws, home):
    for name in ("codex", "gemini", "dsh"):
        h = HarnessSet(hcfg(name=name), ws, CAT).default
        argv = h.argv(values(ws, prompt="SECRET-PROMPT {workspace}"))
        assert h.stdin and not any("SECRET-PROMPT" in a for a in argv), name


def test_dsh_env_relocates_its_homes_and_carries_the_model(ws, home):
    """G-01: a FRESH dsh home per phase under var/harness/dsh/phases/, removed by
    cleanup(); never the shared var/harness/dsh/home a phase could plant a layer in."""
    h = HarnessSet(hcfg(name="dsh", model="m1", endpoint={"base_url": "http://127.0.0.1:1/v1",
                                                         "api_key_env": ""}), ws, CAT).default
    ph = h.phase(values(ws))
    env = h.adapter.env(ph)
    root = Path(env["DSH_HOME"]).parent
    assert root.parent == ws / "var" / "harness" / "dsh" / "phases"
    assert root.name.startswith("01-") and env["DSH_AGENTS_HOME"] == str(root / "agents")
    assert env["KONSTANT_MODEL"] == "m1" and env["KONSTANT_ENDPOINT_KEY"] == "unused"
    h.adapter.prepare(ph)
    assert oct(Path(env["DSH_HOME"]).stat().st_mode & 0o777) == "0o700"
    other = h.phase(values(ws))
    assert h.adapter.env(other)["DSH_HOME"] != env["DSH_HOME"]      # each phase its own
    h.adapter.cleanup(ph)
    h.adapter.cleanup(other)
    assert not root.exists() and not list((ws / "var/harness/dsh/phases").iterdir())


def test_gemini_env_relocates_its_home_and_copies_the_settings(ws, home):
    (ws / ".gemini").mkdir()
    (ws / ".gemini" / "settings.json").write_text('{"context": {}}\n')
    h = HarnessSet(hcfg(name="gemini"), ws, CAT).default
    ph = h.phase(values(ws))
    assert h.adapter.env(ph) == {"GEMINI_CLI_HOME": str(ws / "var" / "harness" / "gemini")}
    h.adapter.prepare(ph)
    assert (ws / "var/harness/gemini/.gemini/settings.json").read_text() == '{"context": {}}\n'


def test_per_type_override_picks_the_harness_by_the_phase_agent(ws, home):
    hs = HarnessSet(hcfg(name="claude", model="sonnet",
                         types={"review": {"name": "codex", "model": "gpt-5.4-mini"},
                                "docs": {"model": "haiku"}}), ws, CAT)
    assert hs.for_agent("coder").name == "claude" and hs.for_agent("coder").model == "sonnet"
    assert hs.for_agent("reviewer").name == "codex"
    assert hs.for_agent("reviewer").model == "gpt-5.4-mini"
    assert hs.for_agent("writer").name == "claude" and hs.for_agent("writer").model == "haiku"
    assert hs.for_agent("orchestrator") is hs.default            # close-out: the default


def test_override_to_another_harness_does_not_inherit_the_default_model(ws, home):
    hs = HarnessSet(hcfg(name="claude", model="sonnet", types={"review": {"name": "dsh"}}), ws, CAT)
    assert hs.for_agent("reviewer").model == ""


def test_explicit_template_wins_and_takes_model(ws, home):
    hs = HarnessSet(hcfg(name="command", command="tool --m {model} {prompt_file}", model="x1"),
                    ws, CAT)
    argv = hs.default.argv(values(ws))
    assert argv[:3] == ["tool", "--m", "x1"]


@pytest.mark.parametrize("h,needle", [
    (dict(name="command"), "needs a command"),
    (dict(name="claude", command="claude -p {prompt}", model="haiku"), "no {model} placeholder"),
    (dict(name="claude", types={"nosuch": {"name": "codex"}}), "not a task type"),
])
def test_resolution_refusals(ws, home, h, needle):
    with pytest.raises(HarnessError, match=needle):
        HarnessSet(hcfg(**h), ws, CAT)


@pytest.mark.parametrize("h,needle", [
    (dict(name="cursor"), "must be one of"),
    (dict(types={"review": {"nmae": "codex"}}), "unknown key 'nmae'"),
    (dict(types={"review": {"name": "nope"}}), "must be one of"),
    (dict(types={"review": "codex"}), "must be a table"),
    (dict(model="bad model;rm"), "not a model name"),
    (dict(endpoint={"base_url": "ftp://x", "api_key_env": ""}), "http(s) URL"),
    (dict(endpoint={"base_url": 'http://a"b/v1', "api_key_env": ""}), "http(s) URL"),
    (dict(endpoint={"base_url": "", "api_key_env": "1BAD"}), "environment variable"),
])
def test_config_refuses_a_bad_harness_table(h, needle):
    with pytest.raises(ConfigError, match=needle.replace("(", r"\(").replace(")", r"\)")):
        check_harness(hcfg(**h), "konstant.toml")


def test_config_accepts_every_adapter_name_and_an_override():
    for name in harnesses.ADAPTERS:
        check_harness(hcfg(name=name, types={"review": {"name": "dsh", "model": "a/b:c"}}), "t")


def test_task_run_override_runs_one_command_for_all_phases(ws, home):
    hs = HarnessSet(hcfg(name="codex"), ws, CAT, override="tool {prompt_file}")
    assert hs.for_agent("reviewer") is hs.default and hs.default.command == "tool {prompt_file}"


def test_check_fails_fast_on_a_broken_template(ws, home):
    with pytest.raises(HarnessError, match="needs \\{prompt\\}"):
        HarnessSet(hcfg(name="command", command="tool --x"), ws, CAT).check()


def test_harness_run_applies_adapter_env_under_konstant_role(ws, home, tmp_path, monkeypatch):
    """A phase of a named adapter: the adapter env and the worker role, through a fake binary."""
    import sys
    fake = tmp_path / "bin" / "dsh"
    fake.parent.mkdir()
    fake.write_text(f"#!{sys.executable}\nimport os, sys\nprint(os.environ['DSH_HOME'], "
                    "os.environ['KONSTANT_ROLE'], sys.stdin.read().strip())\n")
    fake.chmod(0o755)
    import os
    monkeypatch.setenv("PATH", f"{fake.parent}:{os.environ['PATH']}")
    h = HarnessSet(hcfg(name="dsh"), ws, CAT).default
    res = h.run("HELLO", agent="coder", cwd=ws / "projects" / "demo",
                run_dir=ws / "var" / "runs" / "r1", label="01-x")
    out = open(res.log).read()
    dsh_home, role, text = out.split()
    assert res.rc == 0 and (role, text) == ("worker", "HELLO")
    assert Path(dsh_home).parent.parent == ws / "var/harness/dsh/phases"
    assert not Path(dsh_home).exists(), "the phase's dsh home outlived the phase"


def test_reach_levels_are_known_values(ws, home):
    for name, cls in harnesses.ADAPTERS.items():
        a = cls() if name != "command" else cls("x {prompt}")
        r = a.reach(hcfg(name=name), {"sandbox": True})
        assert all(lvl in ("enforced", "partial", "none") for _a, lvl, _d in r.rows()), name
        assert all(d for _a, _l, d in r.rows()), name
    # dsh confines no reads itself; konstant's jail does, so "enforced" only with the jail
    from konstant import jail
    assert harnesses.ADAPTERS["dsh"]().reach(hcfg(), {}, jail=False).reads[0] == "none"
    assert harnesses.ADAPTERS["dsh"]().reach(hcfg(), {}).reads[0] == (
        "enforced" if jail.available() else "none")
    assert harnesses.ADAPTERS["command"]("x").reach(hcfg(), {}).weakest == "none"


def test_harness_class_is_backward_compatible(tmp_path):
    h = Harness("tool {prompt}", workspace=tmp_path)
    assert h.argv({"prompt": "p"}) == ["tool", "p"] and json.dumps(h.name) == '"command"'
