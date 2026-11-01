"""Factory mode confines every harness (docs/LEVEL5.md 2.1, wave L5-2): a job with sealed holdouts
runs each phase inside konstant's jail whatever the harness - claude, codex, gemini, dsh and an
explicit command template - reached through the real adapters with stand-in CLIs.

A4 on every adapter: the fake harness's `peek` mode finds the sealed store masked and `holdout
show` refused. Identity: the phase reads only its own identity's token (worker) and viewer's.
Relocated homes: claude, codex and gemini get a fresh per-phase home holding only their own
credential file (read-only), and the rest of their real home stays masked.
C9: a producer that tries to move the TARGET (`self-ship`) is denied; the target is unchanged."""
from __future__ import annotations

import json
import re
import sys

import pytest

from tests.factory.conftest import (HARNESSES, git_out, logs, run, sealed_job, stub_starts)
from tests.holdout.conftest import REPO, needs_jail



@needs_jail
@pytest.mark.parametrize("harness", HARNESSES)
def test_A4_peek_masked_on_every_harness(fws, harness):
    jid = sealed_job(fws)
    res, rd = run(fws, harness, jid, "peek")
    peeks = [ln for ln in logs(rd).splitlines() if ln.startswith("peek:")]
    assert "peek: var/holdout empty or masked" in peeks, (peeks, res.stderr[-3000:])
    assert "peek: holdout show refused" in peeks, peeks
    assert not any(ln.startswith("peek: READ") for ln in peeks), peeks
    assert res.returncode == 0, res.stderr[-3000:]            # honest after the peek: verified
    assert "(factory mode: every phase jailed)" in res.stderr
    assert re.search(r"\[type:code\] \((?!None\))[^)]+\) run ", res.stderr)   # the reason, not None
    assert fws.json("job", "show", jid)["status"] == "verified"


@needs_jail
@pytest.mark.parametrize("harness", ("claude", "codex", "gemini"))
def test_factory_phase_gets_a_fresh_home_with_only_its_credential(fws, harness):
    jid = sealed_job(fws)
    res, rd = run(fws, harness, jid)
    assert res.returncode == 0, res.stderr[-3000:]
    starts = [s for s in stub_starts(rd) if s["name"] == harness]
    assert starts, res.stderr[-2000:]
    key = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME",
           "gemini": "GEMINI_CLI_HOME"}[harness]
    homes = {s["env"][key] for s in starts}
    assert len(homes) == len(starts)                           # one fresh home per phase
    for h in homes:
        assert f"/var/harness/{harness}/phases/" in h, h
        assert not __import__("os").path.exists(h)             # removed after its phase
    assert all(s["env"]["KONSTANT_IDENTITY"] == "worker" for s in starts)
    assert all(s["env"]["TMPDIR"] and s["env"]["TMPDIR"].endswith("/tmp") for s in starts)
    if harness in ("claude", "codex"):
        assert {s["credential"] for s in starts} == {"READ"}, starts


@needs_jail
@pytest.mark.parametrize("harness", HARNESSES)
def test_factory_phase_reads_only_its_identity_token_and_no_home_secret(fws, harness):
    """Every phase of a holdout job: worker + viewer tokens readable; the privileged roles and
    the other factory identities masked; the harness homes and ~/.ssh masked."""
    jid = sealed_job(fws)
    probe = fws.src / "probe.py"
    probe.write_text(
        "import json, os, pathlib\n"
        "ws = pathlib.Path(os.environ['KONSTANT_HOME'])\n"
        "home = pathlib.Path(os.environ['HOME'])\n"
        "out = {}\n"
        "for p in sorted((ws / 'var' / 'secrets').glob('*.token')) + [\n"
        "        home / '.claude/planted', home / '.codex/planted', home / '.ssh/id_planted',\n"
        "        home / '.claude/.credentials.json', home / '.codex/auth.json']:\n"
        "    try:\n"
        "        out[p.name] = 'READ' if p.read_text().strip() else 'EMPTY'\n"
        "    except OSError as exc:\n"
        "        out[p.name] = type(exc).__name__\n"
        "print('tokens-probe: ' + json.dumps(out, sort_keys=True))\n")
    import os
    hook = fws.src / "sitecustomize.py"           # the fake harness runs the probe first
    hook.write_text(f"import runpy\nrunpy.run_path({str(probe)!r})\n")
    res, rd = run(fws, harness, jid, PYTHONPATH=f"{fws.src}:{os.environ.get('PYTHONPATH', '')}")
    seen = [json.loads(m) for m in re.findall(r"^tokens-probe: (.*)$", logs(rd), re.M)]
    assert seen, (logs(rd)[-2000:], res.stderr[-2000:])
    for s in seen:
        readable = sorted(k for k, v in s.items() if v == "READ")
        assert readable == ["viewer.token", "worker.token"], s
        for t in ("owner.token", "orchestrator.token", "verifier.token", "scenario.token",
                  "planner.token", "dod-reviewer.token", "factory.token"):
            assert s.get(t, "absent") != "READ", (t, s)
        for f in ("planted", "id_planted", ".credentials.json", "auth.json"):
            assert s[f] != "READ", (f, s)


@needs_jail
@pytest.mark.parametrize("harness", ("claude", "command"))
def test_C9_self_ship_cannot_move_the_target(fws, harness):
    target = fws.home / "projects" / "greeter"
    before = git_out(target, "rev-parse", "main")
    jid = sealed_job(fws)
    res, rd = run(fws, harness, jid, "self-ship")
    lines = [ln for ln in logs(rd).splitlines() if ln.startswith("self-ship:")]
    assert lines and all(ln.startswith("self-ship: DENIED") for ln in lines), lines
    assert any("update-ref main" in ln for ln in lines)
    assert git_out(target, "rev-parse", "main") == before
    assert git_out(target, "rev-parse", "-q", "--verify", "refs/heads/self-shipped") == ""
    assert not (target / "SELF-SHIPPED").exists()
    assert res.returncode == 0, res.stderr[-3000:]             # then honest: verified on its clone


def test_C9_red_twin_the_same_attempts_unjailed_move_the_target(fws, capsys):
    """The fake's own self-ship, run outside the jail against the target: it writes a new ref
    and a file there - so the jailed test above is not vacuous."""
    target = fws.home / "projects" / "greeter"
    sys.path.insert(0, str(REPO / "tests" / "fixtures"))
    try:
        import fake_harness
        fake_harness.self_ship(target.parent / "greeter@9")
    finally:
        sys.path.pop(0)
    out = capsys.readouterr().out
    assert "self-ship: WROTE new ref" in out and (target / "SELF-SHIPPED").exists(), out
