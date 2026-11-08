"""No phase reads the vault's files directly (machinery.SEALED): every harness's own permission
system denies it and konstant's jail masks it, so memory reaches a phase only through the board,
which enforces the pools. The verifier never treats memory as evidence: probes refuse vault
paths and the board refuses a close whose check runs a memory command. Red twins: remove
`memory` from machinery.SEALED (or the evidence rule) and each consumer lets it through."""
from __future__ import annotations

import json
import re

import pytest

from konstant import jail, machinery
from konstant.agents import settings
from konstant.harnesses import codex, gemini
from konstant.harnesses.base import Phase


def reach(ws) -> dict:
    vault = ws / "memory"
    rd = json.loads(settings.render(ws, {}))
    ab = settings.abs_rule(ws)
    fs = codex.filesystem(Phase({"workspace": ws, "cwd": ws / "projects" / "demo",
                                 "run_dir": ws / "var" / "runs" / "r1"}))
    gem = False
    for block in gemini.policy(ws, [], "h").split("[[rule]]"):
        if "read_file" in block and 'decision = "deny"' in block:
            pat = json.loads(re.search(r'argsPattern = (".*")', block).group(1))
            gem = all(re.search(pat, json.dumps(a)) for a in (
                {"file_path": f"{vault}/worker/x.md"}, {"dir_path": str(vault)},
                {"pattern": "**/*.md", "path": f"{vault}/verifier"}))
    argv = jail.wrap(["true"], hide=jail.hidden(ws), home=ws)
    masked = any(argv[i] == "--tmpfs" and argv[i + 1] == str(vault.resolve())
                 for i in range(len(argv) - 1))
    return {"jail": masked or not jail.available(),
            "claude tools": f"Read({ab}/memory/**)" in rd["permissions"]["deny"],
            "claude edit": f"Edit({ab}/memory/**)" in rd["permissions"]["deny"],
            "claude sandbox": str(vault) in rd["sandbox"]["filesystem"]["denyRead"],
            "codex": fs.get(f"{vault}/**") == "deny", "gemini": gem}


@pytest.fixture()
def ws(tmp_path):
    w = tmp_path / "ws"
    for d in ("memory/worker", "memory/verifier", "var/secrets", "var/runs/r1",
              "projects/demo"):
        (w / d).mkdir(parents=True)
    (w / "memory/verifier/v.md").write_text("verdict notes\n")
    return w


def test_vault_unreadable_and_unwritable_by_every_phase_reader_green(ws):
    got = reach(ws)
    assert all(got.values()), got
    assert "memory" in machinery.SEALED and "memory" in machinery.DIRS


def test_vault_reach_red_when_memory_leaves_SEALED(ws, monkeypatch):
    monkeypatch.setattr(machinery, "SEALED", tuple(s for s in machinery.SEALED if s != "memory"))
    got = reach(ws)
    assert got["claude tools"] is False and got["claude sandbox"] is False
    assert got["codex"] is False and got["gemini"] is False
    assert got["jail"] is (not jail.available())


def test_probes_never_read_the_vault_red_without_the_rule(ws, monkeypatch):
    from konstant.verify.shapes import Roots
    roots = Roots(home=ws, paths=[ws])
    with pytest.raises(ValueError, match="memory"):
        roots.locate(str(ws / "memory" / "worker" / "x.md"))
    with pytest.raises(ValueError, match="memory"):
        roots.locate("memory")
    monkeypatch.setattr(machinery, "SEALED", tuple(s for s in machinery.SEALED if s != "memory"))
    assert roots.locate(str(ws / "memory" / "worker" / "x.md"))


def test_probe_urls_never_read_the_memory_routes():
    from konstant.verify.shapes import Roots, parse_command
    roots = Roots(home="/tmp", paths=["/tmp"])
    with pytest.raises(ValueError, match="memory"):
        parse_command("curl -s http://127.0.0.1:8470/api/memory/recall?q=x", roots)


@pytest.mark.parametrize("cmd", ["bin/konstant memory recall greet", "konstant memory show x",
                                 "python3 -m konstant mcp memory",
                                 "/ws/bin/konstant --as viewer memory list",
                                 "pytest -q && bin/konstant memory recall done"])
def test_a_close_whose_check_reads_memory_is_refused(cmd):
    from konstant.board import evidence
    assert "memory" in (evidence.memory_problem(cmd) or "")
    probs = evidence.evidence_problems({"verify_cmd": cmd, "verify_exit": 0,
                                        "verify_output": "1 passed"})
    assert any("memory is never evidence" in p for p in probs), probs


def test_a_close_check_without_memory_passes_and_red_twin(monkeypatch):
    from konstant.board import evidence
    for ok in ("pytest -q tests/memory/", "grep -c memoryview src/x.py",
               "python3 -m pytest memory_test.py", "bin/konstant job show 3 --json"):
        assert evidence.memory_problem(ok) is None, ok
    monkeypatch.setattr(evidence, "MEMORY_CMD", re.compile(r"(?!x)x"))
    assert evidence.memory_problem("bin/konstant memory recall greet") is None   # disarmed
