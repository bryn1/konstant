"""Optional embeddings from a LOCAL OpenAI-compatible endpoint (`POST <endpoint>/embeddings`,
as vLLM, llama.cpp `llama-server --embeddings` and Ollama serve it).

`[memory] embed_endpoint` (e.g. a loopback URL ending in /v1) and `embed_model` turn it on;
`embed_api_key_env` names the variable that holds a key when the server wants one. Nothing is
downloaded and no model runs inside konstant: without an endpoint, recall is lexical (index.py).
An endpoint that fails is reported in the recall result (`mode`), never fatal: the note is stored
and indexed lexically, and its vector is computed at the next sync that reaches the endpoint.
"""
from __future__ import annotations

import array
import json
import math
import os
import urllib.error
import urllib.request

BATCH = 32
TIMEOUT_S = 30


class EmbedError(Exception):
    pass


class Embedder:
    def __init__(self, endpoint: str, model: str, api_key_env: str = "",
                 timeout: float = TIMEOUT_S):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout

    @property
    def name(self) -> str:
        return self.model

    def embed(self, texts: list) -> list:
        out = []
        for i in range(0, len(texts), BATCH):
            out += self._call(texts[i:i + BATCH])
        return out

    def _call(self, texts: list) -> list:
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(self.endpoint + "/embeddings", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        key = os.environ.get(self.api_key_env, "") if self.api_key_env else ""
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise EmbedError(f"embedding endpoint answered HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise EmbedError(f"embedding endpoint unreachable "
                             f"({getattr(exc, 'reason', exc)})") from None
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise EmbedError("embedding endpoint returned no vector per input")
        rows = sorted(rows, key=lambda r: r.get("index", 0) if isinstance(r, dict) else 0)
        vecs = []
        for r in rows:
            v = r.get("embedding") if isinstance(r, dict) else None
            if not isinstance(v, list) or not v or not all(isinstance(x, (int, float)) for x in v):
                raise EmbedError("embedding endpoint returned a malformed vector")
            vecs.append([float(x) for x in v])
        return vecs


def from_config(mem: dict):
    """The configured Embedder, or None (lexical recall)."""
    if not (mem.get("embed_endpoint") and mem.get("embed_model")):
        return None
    return Embedder(mem["embed_endpoint"], mem["embed_model"], mem.get("embed_api_key_env", ""))


def pack(vec: list) -> bytes:
    """Unit-normalised float32 bytes (cosine = dot product)."""
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return array.array("f", (x / norm for x in vec)).tobytes()


def unpack(blob: bytes) -> array.array:
    a = array.array("f")
    a.frombytes(blob)
    return a


def cosine(a, b) -> float:
    if len(a) != len(b):
        return -1.0
    return sum(x * y for x, y in zip(a, b))
