"""ONE description of the memory MCP server, rendered into every harness's own configuration
(docs/HARNESSES.md, "Memory"): the server is `<workspace>/bin/konstant mcp memory` (stdio), named
SERVER everywhere, its tools allowed by name and nothing else.

  claude  `.claude/konstant-mcp.json` passed with `--mcp-config` (the default command keeps
          `--strict-mcp-config`, so it is the ONLY MCP server a phase gets) + allow rules
          `mcp__konstant-memory__<tool>` in the generated settings (under dontAsk an unlisted
          tool is denied)
  codex   `-c mcp_servers.konstant-memory.{command,args,env_vars,enabled_tools,...}` on the
          `codex exec` line (`--ignore-user-config` still drops the user's own servers)
  gemini  `mcpServers.konstant-memory` in the generated `.gemini/settings.json` (env passed
          explicitly: Gemini CLI strips variables from an MCP server's environment) + policy
          rules allowing exactly these tools (`mcpName`)
  dsh     an `@deepseek-ai/dsh-mcp-client` row inserted by `.dsh/konstant.patch.yml`
The phase's identity reaches the server through its environment (KONSTANT_IN_TASK,
KONSTANT_IDENTITY, KONSTANT_RUN, KONSTANT_HOME); the server then acts with that identity's
token, which is the only one the phase's jail exposes. `[memory] enabled = false` renders none
of it.
"""
from __future__ import annotations

import json
from pathlib import Path

SERVER = "konstant-memory"
TOOLS = ("kb_recall", "kb_store", "kb_note")
ENV = ("KONSTANT_HOME", "KONSTANT_IN_TASK", "KONSTANT_ROLE", "KONSTANT_IDENTITY", "KONSTANT_RUN",
       "KONSTANT_MEMORY_VIEW", "KONSTANT_MEMORY_OUT")       # the last two: memory/view.py
CLAUDE_CONFIG = ".claude/konstant-mcp.json"


def command(ws) -> tuple:
    return str(Path(ws) / "bin" / "konstant"), ["mcp", "memory"]


def claude_json(ws, enabled: bool = True) -> str:
    servers = {}
    if enabled:
        cmd, args = command(ws)
        servers[SERVER] = {"type": "stdio", "command": cmd, "args": args,
                           "env": {"KONSTANT_HOME": str(ws)}}
    return json.dumps({"mcpServers": servers}, indent=2) + "\n"


def claude_allow(enabled: bool = True) -> list:
    return [f"mcp__{SERVER}__{t}" for t in TOOLS] if enabled else []


def codex_args(ws, enabled: bool = True) -> list:
    if not enabled:
        return []
    cmd, args = command(ws)
    key = f"mcp_servers.{SERVER}"
    return ["-c", f"{key}.command={json.dumps(cmd)}",
            "-c", f"{key}.args={json.dumps(args)}",
            "-c", f"{key}.env_vars={json.dumps(list(ENV))}",
            "-c", f"{key}.enabled_tools={json.dumps(list(TOOLS))}",
            "-c", f'{key}.default_tools_approval_mode="approve"']


def gemini_servers(ws, enabled: bool = True) -> dict:
    if not enabled:
        return {}
    cmd, args = command(ws)
    env = {v: f"${v}" for v in ENV}
    env["KONSTANT_HOME"] = str(ws)
    return {SERVER: {"command": cmd, "args": args, "env": env, "includeTools": list(TOOLS),
                     "trust": False}}


def dsh_lines(ws, enabled: bool = True) -> list:
    if not enabled:
        return []
    cmd, args = command(ws)
    return ["- insert:", f"    - id: {SERVER}", "      name: '@deepseek-ai/dsh-mcp-client'",
            "      config:", f"        serverName: {SERVER}", "        transport: stdio",
            f"        command: {json.dumps(cmd)}", f"        args: {json.dumps(args)}",
            "        env:", f"          KONSTANT_HOME: {json.dumps(str(ws))}"]
