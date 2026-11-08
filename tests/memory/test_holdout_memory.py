"""Memory in a factory job (a job with sealed holdouts, every phase in konstant's jail, through
the real dsh adapter with the stub dsh playing the fake harness's `memory` mode): the producer
cannot read the vault's files, may store and recall ordinary facts, and a held-out literal or a
canary it tries to store is refused AND counted by the verifier against its job (LEAK-SUSPECT ->
FAIL; LEAK -> BLOCKED with the set burned). The control run shows the verdict comes from the
memory refusal alone."""
from __future__ import annotations

import json

from tests.holdout.conftest import hws_manual  # noqa: F401  (fixture)
from tests.holdout.conftest import needs_jail
from tests.holdout.test_runs import canary, sealed


def _log(rd) -> str:
    return "\n".join(p.read_text() for p in sorted((rd / "phases").glob("*.log")))


def _verify(w, jid) -> dict:
    v = w.run("verify", jid, "--json")
    return json.loads(v.stdout)


@needs_jail
def test_control_an_honest_fact_is_stored_and_the_job_verifies(hws_manual):
    w = hws_manual
    w.ok("--as", "owner", "memory", "store", "owner note: greetings stay lower case")
    jid = sealed(w)
    res, rd = w.task_run("memory", jid, FAKE_HARNESS_MEMORY="the greeting helper lives in "
                         "greeter.py")
    assert res.returncode == 0, res.stderr[-2000:]
    log = _log(rd)
    assert "memory: vault empty or masked" in log and "memory: READ" not in log
    assert "memory: STORED STORED shared/worker/facts/" in log
    assert "greeting" in log.split("memory: RECALL", 1)[1]
    data = _verify(w, jid)
    assert data["verdict"] == "PASS", data
    log_rows = w.json("--as", "owner", "memory", "log")["writes"]
    mine = [r for r in log_rows if r["actor"] == "worker"]
    assert mine and mine[0]["state"] == "stored" and mine[0]["job_id"] == int(jid)


@needs_jail
def test_a_held_out_literal_through_memory_fails_the_round(hws_manual):
    w = hws_manual
    jid = sealed(w)
    res, rd = w.task_run("memory", jid, FAKE_HARNESS_MEMORY="tip: the answer is hello Ada")
    assert res.returncode == 0, res.stderr[-2000:]
    assert "memory: REFUSED" in _log(rd)
    data = _verify(w, jid)
    assert data["verdict"] == "FAIL", data
    assert any("LEAK-SUSPECT" in r and "memory" in r for r in data["reasons"]), data["reasons"]
    assert "hello Ada" not in json.dumps(data)            # the verdict never repeats the literal


@needs_jail
def test_a_canary_through_memory_is_a_leak_that_burns_the_set(hws_manual):
    w = hws_manual
    jid = sealed(w)
    res, _rd = w.task_run("memory", jid, FAKE_HARNESS_MEMORY=f"keep {canary(w, jid)}")
    assert res.returncode == 0, res.stderr[-2000:]
    data = _verify(w, jid)
    assert data["verdict"] == "BLOCKED", data
    assert any(r.startswith("LEAK:") and "memory" in r for r in data["reasons"]), data
    states = {r["state"] for r in w.json("holdout", "list", jid)["holdouts"]}
    assert states == {"burned"}
