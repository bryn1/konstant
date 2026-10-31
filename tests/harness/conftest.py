"""Fixtures for the harness adapter tests: a laid-out workspace at a fixed-shape path, a HOME
without the operator's files, and golden-file comparison (KONSTANT_REGEN_GOLDEN=1 rewrites)."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest

from konstant.config import DEFAULTS

REAL_HOME = os.environ.get("HOME", "")
GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "harness"


@pytest.fixture()
def home(tmp_path, monkeypatch) -> Path:
    """An empty HOME: no ~/.ssh, ~/.claude/CLAUDE.md or ~/.codex of the operator leak into a
    rendering or a reach verdict."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return h


@pytest.fixture()
def ws(tmp_path, home) -> Path:
    """A workspace laid out like an install: machinery dirs, the five tokens, a git project and
    a run dir with OUT and TMPDIR."""
    w = tmp_path / "ws"
    for d in ("bin", ".venv", "src", "catalog", "tests", ".claude", "var/secrets",
              "projects/demo/.git/hooks", "var/runs/r1/out", "var/runs/r1/tmp"):
        (w / d).mkdir(parents=True, exist_ok=True)
    for f in ("konstant.toml", "install.sh", "pyproject.toml", "var/board.db", "AGENTS.md",
              "projects/demo/.git/config"):
        (w / f).write_text("x\n")
    for role in ("owner", "orchestrator", "worker", "verifier", "viewer"):
        (w / "var" / "secrets" / f"{role}.token").write_text("t\n")
    return w


def values(ws: Path, prompt: str = "PROMPT") -> dict:
    run = ws / "var" / "runs" / "r1"
    return {"prompt": prompt, "prompt_file": run / "prompts" / "01.md", "agent": "coder",
            "cwd": ws / "projects" / "demo", "run_dir": run, "workspace": ws}


def hcfg(**over) -> dict:
    h = copy.deepcopy(DEFAULTS["harness"])
    h.update(over)
    return h


def norm(text: str, ws: Path, home: Path | None = None) -> str:
    import json
    import re
    for form in (json.dumps(re.escape(str(ws)))[1:-1], re.escape(str(ws)), str(ws)):
        text = text.replace(form, "<WS>")
    return text.replace(str(home), "<HOME>") if home else text


def golden(name: str, text: str) -> None:
    p = GOLDEN / name
    if os.environ.get("KONSTANT_REGEN_GOLDEN") == "1":
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    assert p.is_file(), f"no golden file {p} (KONSTANT_REGEN_GOLDEN=1 writes it)"
    assert text == p.read_text(), f"{name} differs from its golden file"
