"""The scenario writer's memory (owner decision 2026-11-08: it READS the shared pool and writes only
the sealed one), without giving its phase a token (docs/LEVEL5.md 3.4, "L5-3 as built": the
scenario writer reads no token, so it cannot read the board or post anything a producer reads).

Before the phase, konstant (outside the jail, as the `scenario` identity) exports every note that
identity may read into `<drafts>/.memory/view/` (a plain vault); the phase's MCP server runs in
VIEW mode (KONSTANT_MEMORY_VIEW, KONSTANT_MEMORY_OUT): kb_recall searches that copy with its own
index, kb_store / kb_note write Markdown files into `<drafts>/.memory/out/`. After the phase
konstant stores each of those through the board as `scenario` (the sealed pool; the store-time
scan applies as to any write) and removes `.memory/` before the drafts are sealed.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from konstant.memory import note as note_mod
from konstant.memory.index import Index
from konstant.memory.vault import Vault, VaultError, safe_rel

VIEW_ENV, OUT_ENV = "KONSTANT_MEMORY_VIEW", "KONSTANT_MEMORY_OUT"


def prepare(client, drafts: Path) -> dict:
    """Export the readable notes into <drafts>/.memory/view; -> the phase's extra environment
    ({} when memory is off or the board refuses)."""
    from konstant.client import ClientError
    base = Path(drafts) / ".memory"
    view, out = base / "view", base / "out"
    try:
        notes = client.get("/api/memory/export")["notes"]
    except (ClientError, KeyError):
        return {}
    for d in (view, out):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    trust = {n["path"]: {k: n.get(k) for k in ("trust", "verified", "job")} for n in notes}
    (base / "trust.json").write_text(json.dumps(trust), encoding="utf-8")
    for n in notes:
        try:
            p = view / safe_rel(n["path"])
        except VaultError:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(n["text"], encoding="utf-8")
    return {VIEW_ENV: str(view), OUT_ENV: str(out)}


def collect(client, drafts: Path, log=print) -> list:
    """Store the phase's notes as `scenario` (the sealed pool); remove .memory/. -> stored paths."""
    from konstant.client import ClientError
    base = Path(drafts) / ".memory"
    stored = []
    for f in sorted((base / "out").glob("*.md")) if (base / "out").is_dir() else []:
        if f.is_symlink() or not f.is_file():
            continue
        n = note_mod.parse(f.read_text(encoding="utf-8", errors="replace"), f.name)
        try:
            res = client.post("/api/memory/note", {"title": n.title, "text": n.body,
                                                   "tags": n.tags[:16]})
            stored.append(res["path"])
        except ClientError as exc:
            log(f"konstant holdout: a scenario-writer note was not stored: {exc.message}")
    shutil.rmtree(base, ignore_errors=True)
    return stored


class ViewClient:
    """The MCP server's client in VIEW mode: the exported copy instead of the board."""

    def __init__(self, view: str, out: str):
        self.view, self.out = Path(view), Path(out)
        self.index = Index(self.out.parent / "index.db", Vault(self.view))

    def get(self, path: str, /, **params) -> dict:
        if path != "/api/memory/recall":
            from konstant.client import ClientError
            raise ClientError(f"{path}: not available to the scenario writer")
        self.index.sync({})
        hits, mode = self.index.search(params.get("q", ""), None, False,
                                       int(params.get("limit") or 8))
        try:
            trust = json.loads((self.out.parent / "trust.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            trust = {}
        for h in hits:
            h.update(trust.get(h["path"]) or {"trust": "unknown", "verified": None, "job": None})
        hits.sort(key=lambda h: 0 if h.get("verified") else 1)
        return {"query": params.get("q", ""), "mode": f"{mode}, read-only view", "hits": hits}

    def post(self, path: str, body: dict) -> dict:
        title = note_mod.file_title(body.get("title") or note_mod.title_from(body["text"]))
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        p = self.out / f"{stamp} {title}.md"
        meta = {"title": body.get("title") or title, "tags": list(body.get("tags") or [])}
        p.write_text(note_mod.render(meta, body.get("text", "")), encoding="utf-8")
        os.chmod(p, 0o600)
        return {"path": f"(sealed pool, stored after the phase) {p.name}", "commit": "-" * 12,
                "pool": "sealed"}
