"""The optional Chroma engine (`[memory] engine = "chroma"`, `pip install 'konstant[chroma]'`):
same answers, same pool rules (the SQLite catalog filters every Chroma hit), vectors from
the local endpoint only. Without the package the engine refuses with the install line."""
from __future__ import annotations

import importlib.util

import pytest

from tests.memory.conftest import MemBoard
from tests.memory.fake_embed import Endpoint

HAVE = importlib.util.find_spec("chromadb") is not None


def _board(tmp_path, url: str) -> MemBoard:
    mb = MemBoard(tmp_path)
    mb.confine(f'[memory]\nengine = "chroma"\nembed_endpoint = "{url}"\n'
               'embed_model = "fake-embed"\n')
    return mb


@pytest.mark.skipif(HAVE, reason="chromadb is installed here")
def test_chroma_engine_without_the_extra_names_the_install_line(tmp_path):
    with Endpoint() as ep:
        mb = _board(tmp_path, ep.url)
        r = mb.store("worker", "the office cat")
    assert r.status_code == 503 and "konstant[chroma]" in r.text


@pytest.mark.skipif(not HAVE, reason="chromadb not installed (optional extra)")
def test_chroma_engine_hybrid_recall_and_pools(tmp_path):
    with Endpoint() as ep:
        mb = _board(tmp_path, ep.url)
        assert mb.store("worker", "The office cat sleeps on the board.").status_code == 200
        assert mb.store("verifier", "A feline was seen near the verdict.").status_code == 200
        r = mb.recall("worker", "kitten").json()
        assert r["mode"] == "hybrid"
        assert [h["pool"] for h in r["hits"]] == ["shared"]           # the verifier's is sealed
        assert (tmp_path / "var" / "memory" / "chroma").is_dir()
        owner = [h["pool"] for h in mb.recall("owner", "kitten").json()["hits"]]
        assert sorted(owner) == ["sealed", "shared"]
        assert mb.call("orchestrator", "POST", "/api/memory/reindex").json()["embedded"] == 2
        assert mb.recall("worker", "kitten").json()["hits"][0]["pool"] == "shared"
