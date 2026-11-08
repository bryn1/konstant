"""`konstant doctor` rows for memory: the vault, the index engine, the embedding endpoint, what
is served (memory_share). The endpoint check is one GET <endpoint>/models with a short timeout."""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import urllib.error
import urllib.request

from konstant.memory import service


def _fts5() -> bool:
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.Error:
        return False


def _reach(endpoint: str) -> str | None:
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + "/models", timeout=3):
            return None
    except urllib.error.HTTPError as exc:
        return None if exc.code in (401, 403, 404, 405) else f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        return str(getattr(exc, "reason", exc))


def rows(cfg) -> list:
    m = service.settings(cfg)
    if not m["enabled"]:
        return [("INFO", "memory", "off ([memory] enabled = false): no MCP server is generated, "
                 "the memory routes refuse")]
    out = []
    v = service.vault(cfg)
    notes = len(v.files())
    if shutil.which("git") is None:
        out.append(("WARN", "memory", f"{v.root}: git not found: memory writes are refused "
                    "(every write is a commit in memory/.git)"))
    else:
        out.append(("PASS", "memory", f"vault {v.root} ({notes} note(s), its own git repository; "
                    "phases reach it only through the board: `konstant mcp memory`, "
                    "`konstant memory`)"))
    if not _fts5():
        out.append(("WARN", "memory index", "this Python's sqlite3 has no FTS5: recall cannot "
                    "index (use a Python built with a current SQLite)"))
    elif m["engine"] == "chroma" and importlib.util.find_spec("chromadb") is None:
        out.append(("FAIL", "memory index", "[memory] engine = \"chroma\" but chromadb is not "
                    "installed: pip install 'konstant[chroma]' into .venv, or engine = \"sqlite\""))
    else:
        out.append(("PASS", "memory index", f"engine {m['engine']} (SQLite FTS5"
                    + (" + Chroma vectors" if m["engine"] == "chroma" else "")
                    + "), a cache rebuilt from the vault by `konstant memory reindex`"))
    if not m["embed_endpoint"]:
        out.append(("INFO", "memory recall", "lexical (no [memory] embed_endpoint): set a local "
                    "OpenAI-compatible endpoint + embed_model for hybrid recall"))
    else:
        why = _reach(m["embed_endpoint"])
        out.append(("PASS", "memory recall", f"hybrid: {m['embed_model']} at the configured "
                    "endpoint") if why is None else
                   ("WARN", "memory recall", f"the embedding endpoint does not answer ({why}): "
                    "recall falls back to lexical and says so"))
    share = cfg.confinement().memory_share
    out.append(("INFO", "memory share", "on: notes you add or edit in memory/ yourself are "
                "recalled by phases too" if share else "off: phases recall only notes konstant "
                "wrote ([confinement] memory_share)"))
    return out
