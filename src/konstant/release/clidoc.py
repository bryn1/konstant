"""docs/CLI.md rendered from the argparse tree, so the reference cannot drift from `--help`.

`python -m konstant.release clidoc [--write]` prints (or writes) the document; the test
`tests/release/test_clidoc.py::test_cli_doc_parity` renders it again and compares. Help text is
formatted at a fixed width so the output does not depend on the terminal.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

WIDTH = 100
INTRO = """# konstant CLI reference

Generated from `konstant --help` by `python -m konstant.release clidoc --write`; do not edit by
hand (the test `test_cli_doc_parity` fails when this file and the parser disagree).

Every command takes the global flags `--as ROLE`, `--json` and `--config PATH`, before or after the
command. Run commands through `bin/konstant` inside the workspace (it sets `KONSTANT_HOME`).
Exit codes: 0 ok, 1 refused or failed, 2 usage error or not found; `task check`/`task run` add
3 UNMET, 4 BLOCKED, 5 check error; `verify` returns 0 PASS, 3 FAIL, 4 BLOCKED.
"""


def _fixed(parser: argparse.ArgumentParser) -> None:
    parser.formatter_class = lambda prog: argparse.HelpFormatter(prog, width=WIDTH,
                                                                 max_help_position=32)


def _walk(parser: argparse.ArgumentParser, path: list):
    yield path, parser
    for action in parser._actions:                       # noqa: SLF001 - argparse has no API
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, sub in action.choices.items():
                yield from _walk(sub, path + [name])


def render() -> str:
    from konstant.cli.main import build_parser
    old = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = str(WIDTH)
    try:
        parts = [INTRO]
        for path, parser in _walk(build_parser(), ["konstant"]):
            _fixed(parser)
            title = " ".join(path)
            parts.append(f"## `{title}`\n\n```\n{parser.format_help().rstrip()}\n```\n")
        return "\n".join(parts)
    finally:
        if old is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = old


def target(root: Path | None = None) -> Path:
    return (root or Path(__file__).resolve().parents[3]) / "docs" / "CLI.md"
