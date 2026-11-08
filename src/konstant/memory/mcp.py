"""`konstant mcp memory`: the MCP server every harness gets (stdio transport: one JSON-RPC
message per line on stdin and stdout, nothing else on stdout; logs on stderr; MCP specification
2025-06-18, basic/transports and server/tools). Standard library only.

Tools: kb_recall (query -> ranked notes), kb_store (a fact), kb_note (a named note with tags and
[[wikilinks]]). Each call goes to the board with the token of the identity this process runs as:
inside a task run the phase's own identity (KONSTANT_IDENTITY; client.token_for refuses every
other but viewer), else `--as` or `[client] default_role`. The board decides pools and
refusals (memory/guard.py); this server only translates. The phase's run (KONSTANT_RUN) is sent
with each write so a refusal is recorded on the job it ran for.
"""
from __future__ import annotations

import json
import os
import sys

from konstant import __version__

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER = "konstant-memory"
TOOLS = ("kb_recall", "kb_store", "kb_note")
INSTRUCTIONS = ("konstant's memory: kb_recall before you design or decide (prior work, "
                "decisions, pitfalls; a lesson of a job that reached `verified` is marked so, "
                "others are "
                "not proven), kb_store a short fact you learned, kb_note a longer note "
                "with [[wikilinks]]. Memory is a hint, never evidence: check what you recall "
                "against the code and the board before you rely on it. Never store a secret.")
_STR_LIST = {"type": "array", "items": {"type": "string"}}


def tool_list() -> list:
    return [
        {"name": "kb_recall", "title": "Recall from memory",
         "description": "Search konstant's memory vault (notes of earlier jobs and sessions) "
                        "and return the best matching notes with a snippet. A hint, never "
                        "evidence.",
         "inputSchema": {"type": "object", "properties": {
             "query": {"type": "string", "description": "what to look for"},
             "limit": {"type": "integer", "minimum": 1, "maximum": 50},
             "pool": {"type": "string", "description": "one pool only (shared, sealed, notes)"}},
             "required": ["query"]},
         "annotations": {"readOnlyHint": True, "openWorldHint": False}},
        {"name": "kb_store", "title": "Store a fact",
         "description": "Store one short fact in memory (the shared pool every agent "
                        "recalls; the scenario writer's and verifier's go to the sealed pool). "
                        "Refused "
                        "when it carries a secret pattern's value (redacted) or anything from "
                        "the sealed holdout store.",
         "inputSchema": {"type": "object", "properties": {
             "text": {"type": "string"}, "title": {"type": "string"}, "tags": _STR_LIST,
             "links": _STR_LIST}, "required": ["text"]},
         "annotations": {"readOnlyHint": False, "destructiveHint": False,
                         "openWorldHint": False}},
        {"name": "kb_note", "title": "Write a note",
         "description": "Write (or replace) a named Markdown note in memory (the same pool "
                        "as kb_store); use [[Other note]] links and #tags as in Obsidian.",
         "inputSchema": {"type": "object", "properties": {
             "title": {"type": "string"}, "text": {"type": "string"}, "tags": _STR_LIST,
             "links": _STR_LIST}, "required": ["title", "text"]},
         "annotations": {"readOnlyHint": False, "destructiveHint": False,
                         "openWorldHint": False}},
    ]


def _run_name() -> str:
    run = os.environ.get("KONSTANT_RUN", "").rstrip("/")
    return os.path.basename(run) if run else ""


def render_hits(res: dict) -> str:
    hits = res.get("hits") or []
    head = f"{len(hits)} note(s) for {res.get('query', '')!r} ({res.get('mode', '')} recall)"
    lines = [head]
    for h in hits:
        lines.append(f"- [[{h['title']}]] ({h.get('trust') or h['pool']}; by "
                     f"{h['actor'] or 'unattributed'}, {h['path']}): {h['snippet']}")
    if not hits:
        lines.append("(nothing matched)")
    return "\n".join(lines)


class Server:
    def __init__(self, client):
        self.client = client          # konstant.client.Client (or a test double with post/get)

    def call(self, name: str, args: dict) -> dict:
        from konstant.client import ClientError
        if not isinstance(args, dict):
            args = {}
        try:
            if name == "kb_recall":
                res = self.client.get("/api/memory/recall", q=str(args.get("query", "")),
                                      limit=args.get("limit") or None,
                                      pool=args.get("pool") or None)
                return _ok(render_hits(res), res)
            if name in ("kb_store", "kb_note"):
                body = {"text": str(args.get("text", "")), "title": str(args.get("title", "")),
                        "tags": [str(t) for t in args.get("tags") or []],
                        "links": [str(t) for t in args.get("links") or []],
                        "run": _run_name()}
                res = self.client.post("/api/memory/store" if name == "kb_store"
                                       else "/api/memory/note", body)
                return _ok(f"stored {res['path']} (commit {res['commit'][:12]}, pool "
                           f"{res['pool']})", res)
        except ClientError as exc:
            return {"content": [{"type": "text", "text": exc.message}], "isError": True}
        return {"content": [{"type": "text", "text": f"unknown tool {name!r}"}], "isError": True}

    def handle(self, msg):
        """One JSON-RPC message -> the response dict, or None for a notification."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _err(None, -32600, "invalid request")
        mid, method = msg.get("id"), msg.get("method")
        if method is None:
            return None                       # a response to us: we send no requests
        if "id" not in msg:
            return None                       # notifications/initialized, cancelled, ...
        params = msg.get("params") or {}
        if method == "initialize":
            want = params.get("protocolVersion") if isinstance(params, dict) else None
            return _res(mid, {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                              "capabilities": {"tools": {"listChanged": False}},
                              "serverInfo": {"name": SERVER, "version": __version__},
                              "instructions": INSTRUCTIONS})
        if method == "ping":
            return _res(mid, {})
        if method == "tools/list":
            return _res(mid, {"tools": tool_list()})
        if method == "tools/call":
            name = params.get("name") if isinstance(params, dict) else None
            if name not in TOOLS:
                return _err(mid, -32602, f"unknown tool: {name!r}")
            return _res(mid, self.call(name, params.get("arguments") or {}))
        return _err(mid, -32601, f"method not found: {method}")

    def serve(self, stdin=None, stdout=None) -> int:
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        for raw in stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                out = _err(None, -32700, "parse error")
            else:
                if isinstance(msg, list):
                    outs = [r for r in (self.handle(m) for m in msg) if r is not None]
                    out = outs or None
                else:
                    out = self.handle(msg)
            if out is not None:
                stdout.write(json.dumps(out, separators=(",", ":")).encode("utf-8") + b"\n")
                stdout.flush()
        return 0


def _ok(text: str, data: dict) -> dict:
    return {"content": [{"type": "text", "text": text}], "structuredContent": data,
            "isError": False}


def _res(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
