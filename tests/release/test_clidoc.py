"""docs/CLI.md matches the parser (`test_cli_doc_parity`).

Structural parity runs on every Python: one section per command, every option and subcommand of
that parser named in its section, no section for a command that does not exist. The exact text
comparison runs on the Python minor the doc is generated with (argparse wording shifts between
releases)."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pytest

from konstant.cli.main import build_parser
from konstant.release import clidoc

DOC = Path(__file__).resolve().parents[2] / "docs" / "CLI.md"
GENERATED_ON = (3, 10)


def sections(text: str) -> dict:
    parts = re.split(r"^## `([^`]+)`\n", text, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def test_cli_doc_parity_structure():
    doc = sections(DOC.read_text(encoding="utf-8"))
    walked = dict((" ".join(path), p) for path, p in clidoc._walk(build_parser(), ["konstant"]))
    assert set(doc) == set(walked), (set(doc) ^ set(walked))
    for name, parser in walked.items():
        body = doc[name]
        for action in parser._actions:
            for opt in action.option_strings:
                assert opt in body, f"{name}: {opt} missing from docs/CLI.md"
            if isinstance(action, argparse._SubParsersAction):
                for sub in action.choices:
                    assert re.search(rf"^\s+{re.escape(sub)}\b", body, re.M), f"{name}: {sub}"


@pytest.mark.skipif(sys.version_info[:2] != GENERATED_ON,
                    reason="exact argparse text is compared on the generating Python only")
def test_cli_doc_parity():
    assert DOC.read_text(encoding="utf-8") == clidoc.render(), (
        "docs/CLI.md is stale: run `python -m konstant.release clidoc --write`")


def test_parity_goes_red_on_a_missing_option(monkeypatch):
    text = DOC.read_text(encoding="utf-8").replace("--evidence", "--evidense")
    monkeypatch.setattr(Path, "read_text", lambda self, encoding=None: text)
    with pytest.raises(AssertionError, match="--evidence"):
        test_cli_doc_parity_structure()
