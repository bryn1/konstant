"""Memory test harness: the board TestClient workspace (tests/board/conftest.py) plus helpers to
write vault notes by hand (as the owner's own tools would) and to seal a scenario file into the
holdout store directly (the store-time scan reads it)."""
from __future__ import annotations

import pytest

from tests.board.conftest import Board

CANARY = "khc-0123456789abcdef0123"
SCENARIO = """SCENARIO: greet uses the caller's name
KIND: proof
RUN: python3 -c "from greeter import greet; print(greet('Ada'))"
EXPECT_EXIT: 0
EXPECT_OUT: hello Ada Lovelace
HINT: names other than the default are used verbatim
CANARY: {canary}
"""


class MemBoard(Board):
    def store(self, who: str, text: str, **kw):
        return self.call(who, "POST", "/api/memory/store", {"text": text, **kw})

    def note(self, who: str, title: str, text: str, **kw):
        return self.call(who, "POST", "/api/memory/note", {"title": title, "text": text, **kw})

    def recall(self, who: str, q: str, **params):
        qs = "&".join(f"{k}={v}" for k, v in {"q": q, **params}.items())
        return self.call(who, "GET", f"/api/memory/recall?{qs}")

    def paths(self, who: str, q: str) -> list:
        r = self.recall(who, q)
        assert r.status_code == 200, r.text
        return [h["path"] for h in r.json()["hits"]]

    def hand_note(self, rel: str, text: str):
        p = self.home / "memory" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def seal_scenario(self, job: int, text: str):
        d = self.home / "var" / "holdout" / str(job)
        d.mkdir(parents=True, exist_ok=True)
        (d / "H1.scenario").write_text(text)

    def confine(self, toml: str):
        """Rewrite konstant.toml's [confinement] and rebuild the app (the board reads it)."""
        from fastapi.testclient import TestClient

        from konstant import config
        from konstant.board.app import create_app
        (self.home / "konstant.toml").write_text(toml)
        self.cfg = config.load(self.home)
        self.client = TestClient(create_app(self.cfg))


@pytest.fixture()
def mb(tmp_path):
    return MemBoard(tmp_path)
