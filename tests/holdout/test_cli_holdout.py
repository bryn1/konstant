"""`konstant holdout add|list|check|show` and the claim guard through the CLI, against a real
board (docs/LEVEL5.md 3.9 rows A2, A6, A7, A11)."""
from __future__ import annotations

import json

from tests.holdout.conftest import BRIEF, H1, H2, needs_jail

VACUOUS = H1.replace("from greeter import greet; print(greet('Ada'))",
                     "print(chr(104) + 'ello Ada')")      # passes whatever greeter does
IN_DOD = H1.replace("EXPECT_OUT: hello Ada", "EXPECT_OUT: hello world").replace(
    "greet('Ada')", "greet('Bob')")


@needs_jail
def test_A2_list_shows_commitments_and_never_content(hws):
    jid = hws.add_job()
    sealed = hws.seal(jid, H1, H2)
    assert sealed.returncode == 0, sealed.stderr
    res = hws.run("holdout", "list", jid, "--json")
    data = json.loads(res.stdout)
    assert data["count"] == 2 and [r["state"] for r in data["holdouts"]] == ["sealed", "sealed"]
    assert all(len(r["sha256"]) == 64 for r in data["holdouts"])
    for needle in ("khc-", "RUN", "EXPECT", "hello Ada", "greet("):
        assert needle not in res.stdout, needle
    job = hws.run("job", "show", jid, "--json", "--trail").stdout
    assert "khc-" not in job and "hello Ada" not in job
    assert not list(hws.src.glob("*.scenario"))          # the sources were MOVED into the store
    store = hws.home / "var" / "holdout" / str(jid)
    assert oct(store.stat().st_mode)[-3:] == "700"
    assert {oct(f.stat().st_mode)[-3:] for f in store.iterdir()} == {"400"}


@needs_jail
def test_A6_a_proof_that_passes_on_the_base_is_vacuous(hws):
    jid = hws.add_job()
    assert hws.seal(jid, H1, H2).returncode == 0
    res = hws.seal(jid, VACUOUS)
    assert res.returncode == 1 and "VACUOUS: H3 passes before the work" in res.stderr
    assert list(hws.src.glob("*.scenario"))              # a refused source stays where it was


@needs_jail
def test_A7_an_expectation_from_the_dod_is_not_held_out(hws):
    jid = hws.add_job()
    assert hws.seal(jid, H1, H2).returncode == 0
    res = hws.seal(jid, IN_DOD)
    assert res.returncode == 1 and "NOT HELD OUT: H3 expectation appears in the DoD" in res.stderr


def test_A11_claim_refused_without_sealed_holdouts(hws):
    b = hws.src / "brief-req.md"
    b.write_text(BRIEF)
    jid = json.loads(hws.ok("job", "add", "greet by name", "--project", "greeter", "--type",
                            "code", "--brief", b, "--holdout-required", "--json").stdout)["id"]
    res = hws.run("job", "claim", jid)
    assert res.returncode == 1, res
    assert "HTTP 409" in res.stderr and "no holdout sealed" in res.stderr


@needs_jail
def test_A11_green_claim_after_sealing(hws):
    jid = hws.add_job()
    assert hws.seal(jid, H1, H2).returncode == 0
    assert hws.run("job", "claim", jid).returncode == 0


@needs_jail
def test_add_refusals(hws):
    jid = hws.add_job()
    inside = hws.home / "h.scenario"
    inside.write_text(H1)
    res = hws.run("holdout", "add", jid, "--file", inside, "--file", hws.scenario("b", H2))
    assert res.returncode == 1 and "SOURCE INSIDE THE WORKSPACE" in res.stderr
    res = hws.seal(jid, H1)
    assert res.returncode == 1 and "TOO FEW: job 2 would have 1" in res.stderr
    res = hws.run("holdout", "add", jid, "--file", hws.scenario("c", H1), "--file",
                  hws.scenario("d", H2), env=hws.env(KONSTANT_IN_TASK="1"))
    assert res.returncode == 1 and "not available inside a task run" in res.stderr
    res = hws.run("holdout", "add", jid, "--file", hws.scenario("e", H1), "--file",
                  hws.scenario("f", H2), env=hws.env(KONSTANT_NO_JAIL="1"))
    assert res.returncode == 2 and "holdouts need a confined phase" in res.stderr
    assert hws.json("holdout", "list", jid)["count"] == 0


@needs_jail
def test_show_and_check(hws):
    jid = hws.add_job()
    assert hws.seal(jid, H1, H2).returncode == 0
    shown = hws.run("holdout", "show", jid, "H1")
    assert shown.returncode == 0 and "EXPECT_OUT: hello Ada" in shown.stdout
    refused = hws.run("holdout", "show", jid, "H1", env=hws.env(KONSTANT_IN_TASK="1"))
    assert refused.returncode == 1 and "hello Ada" not in refused.stdout + refused.stderr
    ok = hws.run("holdout", "check", jid, "--control")
    assert ok.returncode == 0 and ok.stdout.split() == ["H1:", "ok", "H2:", "ok"], ok
    f = hws.home / "var" / "holdout" / str(jid) / "H1.scenario"
    f.chmod(0o600)
    f.write_text(f.read_text().replace("hello Ada", "hello Bob"))
    bad = hws.run("holdout", "check", jid)
    assert bad.returncode == 1 and "H1: MISMATCH: holdout commitment mismatch" in bad.stdout
