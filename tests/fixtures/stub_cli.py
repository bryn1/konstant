#!/usr/bin/env python3
"""A stand-in for the `claude`, `codex` and `gemini` CLIs with no model (docs/LEVEL5.md 3.9 A4 on
every adapter): installed on PATH under the CLI's name, it receives exactly the argv, env, stdin
and confinement konstant's adapter gives the real CLI, and hands the phase prompt to
tests/fixtures/fake_harness.py (its modes act as the phase's tool calls).

  stub_cli.py NAME ARGS...   claude: the prompt is the last argv item ({prompt});
                             codex, gemini: the prompt is on stdin.
Each start prints one `stub-cli: <json>` line into the phase log (inside the jail nothing else is
writable): the name, the argv and the environment keys the adapter sets (CLAUDE_CONFIG_DIR,
CODEX_HOME, GEMINI_CLI_HOME, TMPDIR, KONSTANT_IDENTITY) plus whether its own credential file is
readable where the adapter put it.
Only the standard library; it never contacts a network or a model.
"""
from __future__ import annotations

import io
import json
import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYS = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "GEMINI_CLI_HOME", "TMPDIR", "KONSTANT_IDENTITY")
CRED = {"claude": ("CLAUDE_CONFIG_DIR", ".credentials.json"), "codex": ("CODEX_HOME", "auth.json")}


def readable(name: str) -> str:
    var, fn = CRED.get(name, ("", ""))
    if not var or not os.environ.get(var):
        return "-"
    try:
        return "READ" if (Path(os.environ[var]) / fn).read_text().strip() else "EMPTY"
    except OSError as exc:
        return type(exc).__name__


def main() -> int:
    name, args = sys.argv[1], sys.argv[2:]
    if "--version" in args:
        print(f"{name} 0.0-stub")
        return 0
    prompt = args[-1] if name == "claude" and args else sys.stdin.read()
    print("stub-cli: " + json.dumps({"name": name,
                                     "argv": args[:-1] if name == "claude" else args,
                                     "env": {k: os.environ.get(k) for k in KEYS},
                                     "credential": readable(name)}), flush=True)
    sys.argv = [str(HERE / "fake_harness.py")]
    sys.stdin = io.StringIO(prompt)
    runpy.run_path(str(HERE / "fake_harness.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def install(bindir, name: str) -> Path:
    """Put this stub on a PATH directory as `name` (claude, codex or gemini); returns its path."""
    p = Path(bindir) / name
    p.write_text(f'#!/bin/sh\nexec {sys.executable} {Path(__file__).resolve()} {name} "$@"\n')
    p.chmod(0o755)
    return p
