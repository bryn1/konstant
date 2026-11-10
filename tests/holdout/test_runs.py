"""Holdout jobs through `task run --harness dsh` (the real dsh adapter, konstant's jail, the stub
dsh playing the fake harness's modes) and `konstant verify`: docs/LEVEL5.md 3.9 rows A4, A5, A8,
A9, A10, A12, A13, plus the refusals that keep a holdout job off an unconfined phase."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from tests.holdout.conftest import H1, H2, REPO, TASK, needs_jail

HINT1 = "names other than the default are used verbatim"


def sealed(w, jid=None):
    jid = jid or w.add_job()
    res = w.seal(jid, H1, H2)
    assert res.returncode == 0, res.stderr
    return jid


def canary(w, jid, hid="H1") -> str:
    text = (w.home / "var" / "holdout" / str(jid) / f"{hid}.scenario").read_text()
    return re.search(r"^CANARY: (\S+)$", text, re.M).group(1)


@needs_jail
def test_A4_peek_finds_the_store_masked_and_show_refused(hws):
    jid = sealed(hws)
    res, rd = hws.task_run("peek", jid)
    logs = "".join(p.read_text() for p in (hws.home / "var" / "runs").glob("*/phases/*.log"))
    peeks = [ln for ln in logs.splitlines() if ln.startswith("peek:")]
    assert "peek: var/holdout empty or masked" in peeks, (peeks, res.stderr[-2000:])
    assert "peek: holdout show refused" in peeks
    assert not any(ln.startswith("peek: READ") for ln in peeks), peeks
    assert canary(hws, jid) not in logs and res.returncode == 0, res.stderr[-2000:]
    prompts = "".join(p.read_text() for p in rd.glob("prompts/*.md"))
    assert "KONSTANT-HOLDOUTS: 2" in prompts and "hello Ada" not in prompts   # told how many


@needs_jail
def test_A4_red_twin_the_same_peek_unconfined_reads_everything(hws, capsys, monkeypatch):
    """What the masked phase would have seen: the fake's own peek, run outside the jail and
    outside a task run, reads the store and `holdout show` - so the green test is not vacuous."""
    jid = sealed(hws)
    monkeypatch.setenv("KONSTANT_HOME", str(hws.home))
    monkeypatch.delenv("KONSTANT_IN_TASK", raising=False)
    sys.path.insert(0, str(REPO / "tests" / "fixtures"))
    try:
        import fake_harness
        fake_harness.peek(str(jid))
    finally:
        sys.path.pop(0)
    out = capsys.readouterr().out
    assert "peek: READ" in out and "peek: READ via holdout show" in out, out
    # the factory e2e's P3 rows (tests/e2e/factory_check.py p3), unjailed: every token readable
    assert "peek-token: owner.token READ" in out and "peek-token: verifier.token READ" in out, out


@needs_jail
def test_A5_A13_overfit_fails_on_the_holdout_and_declined_cannot_excuse_it(hws):
    jid = sealed(hws)
    res, rd = hws.task_run("overfit", jid)
    assert res.returncode == 3, res.stderr[-3000:]                   # verify FAIL after close
    assert hws.run("task", "check", rd, "--offline").returncode == 0  # the visible DoD is met
    show = hws.run("job", "show", jid, "--json", "--trail").stdout
    job = json.loads(show)
    assert job["verifications"][-1]["verdict"] == "FAIL"
    assert any(f"holdout H1 failed (hint: {HINT1})" in t["body"] for t in job["trail"])
    assert show.count("Ada") == 0 and "khc-" not in show
    # A13: a DECLINED row backed by an owner note cannot excuse the holdout failure
    claim = "holdout H1 failed in verification round one"
    out = Path(json.loads((rd / "record.json").read_text())["out"])
    with open(out / "DONE.md", "a") as fh:
        fh.write(f"DECLINED | {claim} | job {jid}\n")
    hws.ok("--as", "owner", "job", "note", jid, f"DECLINED: {claim}")
    chk = hws.run("task", "check", rd)
    assert chk.returncode == 3, chk
    assert f"holdout H1 failed (hint: {HINT1})" in chk.stdout


@needs_jail
def test_A13_red_twin_the_declined_row_does_match_the_finding(hws, monkeypatch):
    """Take `holdouts` out of UNEXCUSABLE and the same DECLINED row excuses the finding: the
    DECLINED machinery would have matched, only the rule's class keeps it."""
    from konstant.client import Client, token_for
    from konstant.config import load
    from konstant.gate import check
    jid = sealed(hws)
    res, rd = hws.task_run("overfit", jid)
    claim = "holdout H1 failed in verification round one"
    out = Path(json.loads((rd / "record.json").read_text())["out"])
    with open(out / "DONE.md", "a") as fh:
        fh.write(f"DECLINED | {claim} | job {jid}\n")
    hws.ok("--as", "owner", "job", "note", jid, f"DECLINED: {claim}")
    cfg = load(hws.home)
    board = check.BoardView(Client(cfg.base_url, token_for(cfg, "viewer")))
    run = check.load_run(rd, board, home=hws.home)
    kept = [f.text for f in check.evaluate(run) if f.rule == "holdouts"]
    assert any(t.startswith("holdout H1 failed") for t in kept)
    monkeypatch.setattr(check, "UNEXCUSABLE", check.UNEXCUSABLE - {"holdouts"})
    kept = [f.text for f in check.evaluate(run) if f.rule == "holdouts"]
    assert not any(t.startswith("holdout H1 failed") for t in kept), kept


@needs_jail
def test_A8_a_leaked_canary_blocks_and_burns_the_set(hws_manual):
    w = hws_manual
    jid = sealed(w)
    res, _rd = w.task_run("leak", jid, FAKE_HARNESS_CANARY=canary(w, jid))
    assert res.returncode == 0, res.stderr[-2000:]                      # closed, not verified
    v = w.run("verify", jid, "--json")
    data = json.loads(v.stdout)
    assert v.returncode == 4 and data["verdict"] == "BLOCKED", data
    assert "LEAK: canary of H1 found in greeter.py" in data["reasons"]
    states = [r["state"] for r in w.json("holdout", "list", jid)["holdouts"]]
    assert states == ["burned", "burned"]
    assert w.json("job", "show", jid)["status"] == "completed_unverified"


@needs_jail
def test_A9_an_edited_sealed_file_is_a_commitment_mismatch(hws_manual):
    w = hws_manual
    jid = sealed(w)
    res, _rd = w.task_run("", jid)
    assert res.returncode == 0, res.stderr[-2000:]
    f = w.home / "var" / "holdout" / str(jid) / "H1.scenario"
    os.chmod(f, 0o600)
    f.write_text(f.read_text().replace("hello Ada", "hello world"))
    data = json.loads(w.run("verify", jid, "--json").stdout)
    assert data["verdict"] == "BLOCKED"
    assert any(r.startswith("holdout commitment mismatch: H1") for r in data["reasons"]), data


@needs_jail
def test_A10_an_honest_run_passes_on_the_closed_commit_without_network(hws_manual):
    w = hws_manual
    jid = sealed(w)
    res, _rd = w.task_run("", jid)
    assert res.returncode == 0, res.stderr[-2000:]
    commit = w.json("job", "show", jid)["evidence"]["commit"]
    assert re.fullmatch(r"[0-9a-f]{40}", commit or "")
    v = w.run("verify", jid, "--json")
    data = json.loads(v.stdout)
    assert v.returncode == 0 and data["verdict"] == "PASS", data
    rows = data["holdouts"]["rows"]
    assert len(rows) == 2 and all(r["commit"] == commit and r["net"] is False
                                  and r["passed"] for r in rows)
    assert w.json("job", "show", jid)["status"] == "verified"


@needs_jail
def test_A12_no_jail_no_holdout_run(hws):
    jid = sealed(hws)
    res, _rd = hws.task_run("", jid, KONSTANT_NO_JAIL="1")
    assert res.returncode == 2 and "holdouts need a confined phase" in res.stderr, res.stderr
    assert hws.json("job", "show", jid)["status"] == "queued"            # nothing claimed


@needs_jail
def test_holdout_job_runs_confined_on_a_command_template_and_is_refused_in_a_session(hws):
    """L5-2 lifted L5-1's "only dsh" restriction: in factory mode an explicit command template
    runs inside konstant's jail too (tests/factory covers every harness). An interactive session
    (`task gate`) is still not confined and is still refused."""
    jid = sealed(hws)
    gate = hws.run("task", "gate", TASK, "--job", jid)
    assert gate.returncode == 2 and "an interactive session is not confined" in gate.stderr
    assert hws.json("job", "show", jid)["status"] == "queued"
    fake = f"{sys.executable} {REPO / 'tests' / 'fixtures' / 'fake_harness.py'} {{prompt_file}}"
    import subprocess
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run", TASK, "--job",
                          str(jid), "--harness", fake], capture_output=True, text=True,
                         env=hws.henv(), timeout=600, cwd=str(hws.home))
    assert res.returncode == 0 and "factory mode: every phase jailed" in res.stderr, res.stderr
    assert hws.json("job", "show", jid)["status"] == "verified"
