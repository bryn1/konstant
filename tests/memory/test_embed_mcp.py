"""Optional embeddings (a local OpenAI-compatible endpoint; lexical fallback) and the MCP
server's protocol (stdio JSON-RPC, MCP 2025-06-18)."""
from __future__ import annotations

import io
import json

from konstant.client import ClientError
from konstant.memory import embed
from konstant.memory.index import Index
from konstant.memory.mcp import PROTOCOLS, Server
from konstant.memory.vault import Vault
from tests.memory.fake_embed import Endpoint


def _idx(tmp_path):
    v = Vault(tmp_path / "memory")
    v.write("worker/Pets.md", "---\ntitle: Pets\n---\nThe office cat sleeps on the board.\n",
            "worker", "m")
    v.write("worker/Net.md", "---\ntitle: Net\n---\nThe proxy listens on a high port.\n",
            "worker", "m")
    return Index(tmp_path / "idx.db", v)


def test_hybrid_recall_finds_what_lexical_cannot(tmp_path):
    idx = _idx(tmp_path)
    with Endpoint() as ep:
        e = embed.Embedder(ep.url, "fake-embed")
        assert idx.sync({}, e)["embedded"] == 2
        lexical, mode = idx.search("feline", attributed_only=False)
        assert lexical == [] and mode == "lexical"
        hits, mode = idx.search("feline", attributed_only=False, embedder=e)
        assert mode == "hybrid" and hits[0]["path"] == "worker/Pets.md"
        assert ep.calls[0][1]["model"] == "fake-embed"


def test_endpoint_down_falls_back_to_lexical_and_says_why(tmp_path):
    idx = _idx(tmp_path)
    dead = embed.Embedder("http://127.0.0.1:9/v1", "m", timeout=2)
    stats = idx.sync({}, dead)
    assert stats["indexed"] == 2 and "unreachable" in stats["embed_error"]
    hits, mode = idx.search("port", attributed_only=False, embedder=dead)
    assert mode.startswith("lexical (") and hits[0]["path"] == "worker/Net.md"


def test_no_endpoint_configured_means_no_embedder():
    assert embed.from_config({"embed_endpoint": "", "embed_model": ""}) is None
    assert embed.from_config({"embed_endpoint": "http://127.0.0.1:1/v1", "embed_model": ""}) \
        is None


class FakeClient:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def get(self, path, **params):
        self.calls.append(("GET", path, params))
        if self.fail:
            raise ClientError("board unreachable at http://127.0.0.1:1")
        return {"query": params["q"], "mode": "lexical", "hits": [
            {"title": "Ports", "pool": "shared", "actor": "worker",
             "path": "worker/Ports.md", "snippet": "the [port] clashes"}]}

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        return {"path": "worker/facts/x.md", "commit": "c" * 40, "pool": "shared"}


def rpc(server, *msgs) -> list:
    out = io.BytesIO()
    server.serve(io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in msgs)), out)
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_mcp_handshake_list_and_call(monkeypatch):
    monkeypatch.setenv("KONSTANT_RUN", "/ws/var/runs/20261102-run1")
    c = FakeClient()
    res = rpc(Server(c),
              {"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                          "clientInfo": {"name": "t", "version": "0"}}},
              {"jsonrpc": "2.0", "method": "notifications/initialized"},
              {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
              {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
               "params": {"name": "kb_recall", "arguments": {"query": "port"}}},
              {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
               "params": {"name": "kb_store", "arguments": {"text": "x", "tags": ["a"]}}},
              {"jsonrpc": "2.0", "id": 5, "method": "nope"})
    assert [r["id"] for r in res] == [1, 2, 3, 4, 5]          # no reply to the notification
    assert res[0]["result"]["protocolVersion"] == "2025-03-26"
    assert res[0]["result"]["serverInfo"]["name"] == "konstant-memory"
    assert [t["name"] for t in res[1]["result"]["tools"]] == ["kb_recall", "kb_store", "kb_note"]
    assert "[[Ports]]" in res[2]["result"]["content"][0]["text"]
    assert res[3]["result"]["isError"] is False
    assert c.calls[1] == ("POST", "/api/memory/store", {"text": "x", "title": "", "tags": ["a"],
                                                        "links": [], "run": "20261102-run1"})
    assert res[4]["error"]["code"] == -32601


def test_mcp_unknown_protocol_gets_the_newest_and_errors_are_tool_errors():
    res = rpc(Server(FakeClient(fail=True)),
              {"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "1999-01-01"}},
              {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
               "params": {"name": "kb_recall", "arguments": {"query": "x"}}},
              {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "rm"}})
    assert res[0]["result"]["protocolVersion"] == PROTOCOLS[0]
    assert res[1]["result"]["isError"] is True and "unreachable" in \
        res[1]["result"]["content"][0]["text"]
    assert res[2]["error"]["code"] == -32602


def test_mcp_stdout_holds_only_messages_even_on_garbage():
    out = io.BytesIO()
    garbage = b"not json\n\n" + json.dumps({"jsonrpc": "1.0", "id": 7}).encode() + b"\n"
    Server(FakeClient()).serve(io.BytesIO(garbage), out)
    lines = out.getvalue().splitlines()
    assert [json.loads(x)["error"]["code"] for x in lines] == [-32700, -32600]
