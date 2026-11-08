"""A loopback stand-in for a local OpenAI-compatible embedding endpoint (POST /v1/embeddings).
Its 'model' maps words to concepts (cat = feline = kitten), so a vector recall finds a note a
lexical recall cannot: the test of the hybrid path needs no real model."""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONCEPTS = {"cat": 0, "feline": 0, "kitten": 0, "cats": 0, "dog": 1, "canine": 1, "puppy": 1,
            "port": 2, "board": 3}
DIM = 8


def vector(text: str) -> list:
    v = [0.0] * DIM
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in CONCEPTS:
            v[CONCEPTS[w]] += 1.0
    v[DIM - 1] += 0.01
    return v


class Endpoint:
    def __init__(self):
        calls = self.calls = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, body, self.headers.get("Authorization")))
                if self.path != "/v1/embeddings":
                    self.send_response(404)
                    self.end_headers()
                    return
                data = [{"index": i, "embedding": vector(t)} for i, t in enumerate(body["input"])]
                out = json.dumps({"data": data, "model": body["model"]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()
