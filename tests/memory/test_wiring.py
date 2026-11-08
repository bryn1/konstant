"""Every harness adapter's generated configuration names konstant's ONE memory MCP server
(`bin/konstant mcp memory`) and allows exactly its tools; `[memory] enabled = false` renders
none of it."""
from __future__ import annotations

import json
import shlex

import pytest

from konstant import config
from konstant.agents import settings
from konstant.harnesses import ADAPTERS, codex, dsh, gemini
from konstant.harnesses.base import Phase
from konstant.memory import wiring

TOOLS = ["kb_recall", "kb_store", "kb_note"]


def phase(ws) -> Phase:
    return Phase({"workspace": ws, "cwd": ws / "projects" / "demo", "run_dir": ws / "var/runs/r",
                  "prompt": "p", "prompt_file": str(ws / "p.md"), "agent": "coder"})


@pytest.fixture()
def ws(tmp_path):
    for d in ("projects/demo", "var/runs/r", "bin"):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


def test_claude_default_command_loads_only_konstants_mcp_config(ws):
    argv = ADAPTERS["claude"]().argv(phase(ws))
    i = argv.index("--mcp-config")
    assert argv[i + 1] == str(ws / ".claude" / "konstant-mcp.json")
    assert "--strict-mcp-config" in argv and argv[i + 2].startswith("--")   # variadic option
    data = json.loads(wiring.claude_json(ws))
    srv = data["mcpServers"]["konstant-memory"]
    assert [srv["command"], *srv["args"]] == [str(ws / "bin" / "konstant"), "mcp", "memory"]
    assert json.loads(wiring.claude_json(ws, enabled=False)) == {"mcpServers": {}}


def test_claude_settings_allow_exactly_the_memory_tools_and_the_cli_fallback(ws):
    allow = json.loads(settings.render(ws, {}))["permissions"]["allow"]
    assert [a for a in allow if a.startswith("mcp__")] == \
        [f"mcp__konstant-memory__{t}" for t in TOOLS]
    assert f"Bash(bin/konstant memory recall *)" in allow
    off = json.loads(settings.render(ws, {}, memory=False))["permissions"]["allow"]
    assert not [a for a in off if a.startswith("mcp__")]


def test_codex_exec_line_carries_the_server(ws):
    argv = codex.Codex().argv(phase(ws))
    cs = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert f'mcp_servers.konstant-memory.command="{ws}/bin/konstant"' in cs
    assert 'mcp_servers.konstant-memory.args=["mcp", "memory"]' in cs
    assert any(c.startswith("mcp_servers.konstant-memory.env_vars=") and "KONSTANT_IDENTITY" in c
               for c in cs)
    assert 'mcp_servers.konstant-memory.enabled_tools=["kb_recall", "kb_store", "kb_note"]' in cs
    assert "--ignore-user-config" in argv
    ph = phase(ws)
    ph.memory = False
    assert not any("mcp_servers" in a for a in codex.Codex().argv(ph))


def test_gemini_settings_and_policy(ws):
    data = json.loads(gemini.settings_json(ws))
    srv = data["mcpServers"]["konstant-memory"]
    assert srv["includeTools"] == TOOLS and srv["env"]["KONSTANT_IDENTITY"] == \
        "$KONSTANT_IDENTITY" and srv["env"]["KONSTANT_HOME"] == str(ws)
    pol = gemini.policy(ws, [], "h")
    for t in TOOLS:
        assert f'mcpName = "konstant-memory"\ntoolName = "{t}"\ndecision = "allow"' in pol
    assert "mcpServers" not in json.loads(gemini.settings_json(ws, enabled=False))
    assert 'mcpName = "konstant-memory"' not in gemini.policy(ws, [], "h", memory=False)


def test_dsh_patch_inserts_the_mcp_client_row(ws):
    text = dsh.patch(ws, {"name": "dsh"}, "h")
    import yaml
    rows = yaml.safe_load(text.replace("!!js process.cwd()", "cwd"))
    ins = [r for r in rows if "insert" in r]
    assert len(ins) == 1
    row = ins[0]["insert"][0]
    assert row["name"] == "@deepseek-ai/dsh-mcp-client" and row["id"] == "konstant-memory"
    c = row["config"]
    assert (c["serverName"], c["transport"], c["command"], c["args"]) == \
        ("konstant-memory", "stdio", str(ws / "bin" / "konstant"), ["mcp", "memory"])
    assert "- insert:" not in dsh.patch(ws, {"name": "dsh"}, "h", memory=False)


def test_memory_config_is_validated(tmp_path):
    (tmp_path / "konstant.toml").write_text('[memory]\nembed_endpoint = "file:///etc/passwd"\n')
    with pytest.raises(config.ConfigError, match="embed_endpoint"):
        config.load(tmp_path)
    (tmp_path / "konstant.toml").write_text('[memory]\nembed_endpoint = "http://127.0.0.1:1/v1"\n')
    with pytest.raises(config.ConfigError, match="embed_model"):
        config.load(tmp_path)
    (tmp_path / "konstant.toml").write_text('[memory]\nmax_note_bytes = 0\n')
    with pytest.raises(config.ConfigError, match="max_note_bytes"):
        config.load(tmp_path)
    (tmp_path / "konstant.toml").write_text('[memory]\nengine = "faiss"\n')
    with pytest.raises(config.ConfigError, match="engine"):
        config.load(tmp_path)


def test_the_mcp_command_line_is_one_documented_cli_verb(ws):
    cmd, args = wiring.command(ws)
    assert shlex.join([cmd, *args]).endswith("bin/konstant mcp memory")
