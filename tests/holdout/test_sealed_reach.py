"""A3 (docs/LEVEL5.md 3.3): every reader a producing phase has is denied the sealed store - the
jail, the Claude Code settings, the codex profile and the gemini policy - and each goes red when
machinery.SEALED is emptied (the one list every consumer reads)."""
from __future__ import annotations

import json
import re

import pytest

from konstant import jail, machinery
from konstant.agents import settings
from konstant.harnesses import codex, gemini
from konstant.harnesses.base import Phase


def reach(ws) -> dict:
    """{consumer: True when it denies reading <ws>/var/holdout}."""
    store = ws / "var" / "holdout"
    rd = json.loads(settings.render(ws, {}))
    ab = settings.abs_rule(ws)
    claude_tools = f"Read({ab}/var/holdout/**)" in rd["permissions"]["deny"]
    claude_sandbox = str(store) in rd["sandbox"]["filesystem"]["denyRead"]
    fs = codex.filesystem(Phase({"workspace": ws, "cwd": ws / "projects" / "demo",
                                 "run_dir": ws / "var" / "runs" / "r1"}))
    codex_deny = fs.get(f"{store}/**") == "deny"
    pol = gemini.policy(ws, [], "h")
    gem = False
    for block in pol.split("[[rule]]"):
        if "read_file" in block and 'decision = "deny"' in block:
            pat = json.loads(re.search(r'argsPattern = (".*")', block).group(1))
            gem = all(re.search(pat, json.dumps(a)) for a in (
                {"file_path": f"{store}/2/H1.scenario"}, {"dir_path": str(store)},
                {"pattern": "**/*", "path": f"{store}/2"},
                {"paths": [f"{store}/2/H1.scenario"]}))
    argv = jail.wrap(["true"], hide=jail.hidden(ws), home=ws)
    masked = any(argv[i] == "--tmpfs" and argv[i + 1] == str(store.resolve())
                 for i in range(len(argv) - 1))
    return {"jail": masked or not jail.available(), "claude tools": claude_tools,
            "claude sandbox": claude_sandbox, "codex": codex_deny, "gemini": gem}


@pytest.fixture()
def ws(tmp_path):
    w = tmp_path / "ws"
    for d in ("var/holdout/2", "var/secrets", "var/runs/r1", "projects/demo"):
        (w / d).mkdir(parents=True)
    (w / "var/holdout/2/H1.scenario").write_text("x\n")
    return w


def test_sealed_store_denied_by_every_reader_green(ws):
    got = reach(ws)
    assert all(got.values()), got
    assert "var/holdout" in machinery.SEALED and "var/holdout" in machinery.DIRS


def test_sealed_store_reach_red_when_SEALED_is_emptied(ws, monkeypatch):
    monkeypatch.setattr(machinery, "SEALED", ())
    got = reach(ws)
    expect_jail = not jail.available()             # without bwrap the jail row cannot go red
    assert got == {"jail": expect_jail, "claude tools": False, "claude sandbox": False,
                   "codex": False, "gemini": False}, got


def test_probes_never_read_the_store(ws):
    from konstant.verify.shapes import Roots
    roots = Roots(home=ws, paths=[ws])
    with pytest.raises(ValueError, match="var/"):
        roots.locate(str(ws / "var" / "holdout" / "2" / "H1.scenario"))
