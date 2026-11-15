"""A scripted OpenAI-compatible chat endpoint with NO model (the live pre-flight,
factory/preflight.py): a harness talking to it runs a real phase whose "model" answers every
conversation that offers a `bash` tool with the next scripted command as a tool call, and with a
plain final answer once the script is done (or when no `bash` tool is offered: a title or
summary request). What the harness's real tool path returns for each command (its stdout,
stderr and exit code, as the harness reports it to a model) is kept in `results`.

It speaks the subset a dsh provider of `api: openai-completions` uses: `GET /models` and
`POST /chat/completions` with `stream: true` (server-sent events: one chunk with the tool call
or the text, one with `finish_reason`, one with `usage`, then `[DONE]`), and the same reply as one
JSON body when `stream` is false. It binds 127.0.0.1 on a free port and never calls out.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "konstant-preflight"


def _text(content) -> str:
    """A message's content as text (a string, or a list of `{type: text, text}` parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


class ScriptedEndpoint:
    def __init__(self, commands: list, final: str = "PREFLIGHT-DONE", model: str = MODEL):
        self.commands, self.final, self.model = list(commands), final, model
        self.results: dict = {}          # command index -> the tool result text the harness sent
        self.prompts: list = []          # the first user message of each conversation
        self.requests = 0
        self._lock = threading.Lock()
        self._server = None

    # --- the reply -----------------------------------------------------------------------
    def reply(self, body: dict) -> dict:
        """{"tool": (call id, name, arguments)} or {"text": str} for one chat request."""
        msgs = body.get("messages") or []
        tools = [((t.get("function") or {}).get("name")) for t in body.get("tools") or []]
        done = [m for m in msgs if m.get("role") == "tool"]
        with self._lock:
            self.requests += 1
            users = [m for m in msgs if m.get("role") == "user"]
            if users and not done:
                self.prompts.append(_text(users[0].get("content")))
            for i, m in enumerate(done):
                self.results.setdefault(i, _text(m.get("content")))
        n = len(done)
        if "bash" in tools and n < len(self.commands):
            args = {"description": f"konstant live pre-flight step {n + 1}",
                    "command": self.commands[n], "timeoutMs": 120000}
            return {"tool": (f"call_preflight_{n + 1}", "bash", json.dumps(args))}
        return {"text": self.final}

    def chunks(self, r: dict) -> list:
        base = {"id": "chatcmpl-preflight", "object": "chat.completion.chunk", "created": 0,
                "model": self.model}
        if "tool" in r:
            cid, name, args = r["tool"]
            delta = {"role": "assistant", "content": None, "tool_calls": [
                {"index": 0, "id": cid, "type": "function",
                 "function": {"name": name, "arguments": args}}]}
            finish = "tool_calls"
        else:
            delta, finish = {"role": "assistant", "content": r["text"]}, "stop"
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        return [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                {**base, "choices": [], "usage": usage}]

    def message(self, r: dict) -> dict:
        msg = {"role": "assistant", "content": r.get("text")}
        if "tool" in r:
            cid, name, args = r["tool"]
            msg["tool_calls"] = [{"id": cid, "type": "function",
                                  "function": {"name": name, "arguments": args}}]
        return {"id": "chatcmpl-preflight", "object": "chat.completion", "created": 0,
                "model": self.model, "choices": [{"index": 0, "message": msg, "finish_reason":
                                                  "tool_calls" if "tool" in r else "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

    # --- the server ----------------------------------------------------------------------
    def start(self) -> str:
        ep = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):          # quiet: konstant prints its own report
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.rstrip("/").endswith("/models"):
                    self._send(200, json.dumps({"object": "list", "data": [
                        {"id": ep.model, "object": "model", "owned_by": "konstant"}]}).encode())
                else:
                    self._send(404, b"{}")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._send(400, b"{}")
                if not self.path.rstrip("/").endswith("/chat/completions"):
                    return self._send(404, b"{}")
                r = ep.reply(body)
                if not body.get("stream"):
                    return self._send(200, json.dumps(ep.message(r)).encode())
                data = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n"
                                for c in ep.chunks(r)) + b"data: [DONE]\n\n"
                self._send(200, data, "text/event-stream")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
