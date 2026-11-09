"""Auto-ship to a local branch (docs/LEVEL5.md 5.6 C1-C8, C10; wave L5-4). $T = projects/greeter
(the TARGET, `main` checked out), each job a holdout job run by the fake harness through the real
dsh adapter to `verified`. Every refusal has a red row (the planted bad state) beside the green
one; on dec6e37 (before this wave) every test here fails: there is no `konstant ship`."""
from __future__ import annotations

import json
import os
import subprocess
import zlib
from pathlib import Path

from tests.holdout.conftest import needs_jail
from tests.ship.conftest import H3, H4, README_PROBE, commit_in, git_out, git_rc


def _rules(res: dict) -> dict:
    return {(r.get("side", "code"), r["rule"]): r for r in res["rules"]}


@needs_jail
def test_C1_dry_run_lists_every_rule_ok_and_moves_nothing(sws):
    jid = sws.verified_job()
    c, pre = sws.commit(jid), git_out(sws.target, "rev-parse", "main")
    r = sws.ship(jid, "--dry-run", "--json")
    res = json.loads(r.stdout)
    assert r.returncode == 0 and res["decision"] == "ship", res
    assert res["commit"] == c and res["pre"] == pre
    assert all(x["ok"] for x in res["rules"]), [x for x in res["rules"] if not x["ok"]]
    names = {k for k in _rules(res)}
    for want in (("code", "verified"), ("code", "holdouts"), ("code", "commit"), ("code", "import"),
                 ("code", "catalog"), ("code", "decision"), ("code", "base"),
                 ("board", "verified"), ("board", "holdouts"), ("board", "commit"),
                 ("board", "base"), ("board", "decision"), ("board", "catalog")):
        assert want in names, want
    assert git_out(sws.target, "rev-parse", "main") == pre and sws.ships() == []


@needs_jail
def test_C2_ship_moves_the_target_to_the_verified_commit(sws):
    jid = sws.verified_job()
    c = sws.commit(jid)
    r = sws.ship(jid, "--json")
    assert r.returncode == 0, r.stderr + r.stdout[-2000:]
    assert git_out(sws.target, "rev-parse", "main") == c
    ships = sws.ships()
    assert len(ships) == 1 and ships[0]["state"] == "shipped" and ships[0]["commit_sha"] == c
    assert ships[0]["post"]["ok"] is True
    checks = {x["check"] for x in ships[0]["post"]["checks"]}
    assert {"probe", "tests", "regression"} <= checks
    # the checked-out worktree was rewritten by konstant (no checkout): content == the commit
    assert (sws.target / "greeter.py").read_bytes() == \
        subprocess.run(["git", "-C", str(sws.target), "cat-file", "blob", f"{c}:greeter.py"],
                       capture_output=True).stdout
    assert any(e["event"] == "SHIPPED" for e in sws.events())
    assert sws.job(jid)["status"] == "verified"


@needs_jail
def test_C3_a_level4_job_without_holdouts_is_refused(sws):
    b = sws.w.src / "l4.md"
    from tests.holdout.conftest import BRIEF
    b.write_text(BRIEF)
    jid = json.loads(sws.w.ok("job", "add", "greet by name", "--project", "greeter", "--type",
                              "code", "--brief", b, "--json").stdout)["id"]
    run_env = sws.w.henv()
    res = subprocess.run([sws_python(), "-m", "konstant", "task", "run", "[type:code] add greet",
                          "--job", str(jid), "--harness", "dsh"], capture_output=True, text=True,
                         env=run_env, timeout=900, cwd=str(sws.w.home))
    assert res.returncode == 0, res.stderr[-2000:]
    assert sws.job(jid)["status"] == "verified"
    before = git_out(sws.target, "rev-parse", "main")
    r = sws.ship(jid)
    assert r.returncode == 1 and "refused: no holdout PASS for commit" in r.stderr, r.stderr
    assert git_out(sws.target, "rev-parse", "main") == before and sws.ships() == []


def sws_python() -> str:
    import sys
    return sys.executable


@needs_jail
def test_C4_holdouts_on_another_commit_than_the_evidence_are_refused_both_sides(sws):
    jid = sws.verified_job()
    c = sws.commit(jid)
    base = git_out(sws.target, "rev-parse", "main")
    # red: the evidence is made to name another commit (a board-level tamper)
    sws.sql("UPDATE jobs SET evidence_json = json_set(evidence_json, '$.commit', ?) WHERE id=?",
            (base, jid))
    r = sws.ship(jid)
    assert r.returncode == 1, r.stdout
    assert f"refused: holdouts ran on {c}, the evidence names {base}" in r.stderr, r.stderr
    assert git_out(sws.target, "rev-parse", "main") == base
    # the board refuses on its own, even when the factory process is bypassed
    from tests.ship.test_ship_units import board_post
    out = board_post(sws, f"/api/jobs/{jid}/ships", {"commit": c, "pre": base, "target": "branch",
                                                    "branch": "main"})
    assert out["decision"] == "refused" and "ship" not in out
    assert any(x["rule"] == "commit" and not x["ok"] for x in out["rules"]), out
    # green twin: the evidence back on the commit the holdouts ran on ships
    sws.sql("UPDATE jobs SET evidence_json = json_set(evidence_json, '$.commit', ?) WHERE id=?",
            (c, jid))
    assert sws.ship(jid).returncode == 0
    assert git_out(sws.target, "rev-parse", "main") == c


@needs_jail
def test_C4b_a_holdout_row_that_ran_on_a_different_commit_is_refused(sws):
    jid = sws.verified_job()
    base = git_out(sws.target, "rev-parse", "main")
    sws.sql("UPDATE verifications SET holdout_json = json_set(holdout_json, '$.rows[0].commit', ?)"
            " WHERE job_id=?", (base, jid))
    r = sws.ship(jid)
    assert r.returncode == 1 and "refused: the holdouts ran on more than one commit" in r.stderr
    assert git_out(sws.target, "rev-parse", "main") == base


@needs_jail
def test_C5_C6_post_ship_failure_rolls_back_without_rewriting_history(sws):
    jid = sws.verified_job("ship-break")
    c, pre = sws.commit(jid), git_out(sws.target, "rev-parse", "main")
    r = sws.ship(jid, "--json")
    assert r.returncode == 3, r.stderr + r.stdout[-2000:]
    s = sws.ships()[0]
    assert s["state"] == "rolled_back" and s["commit_sha"] == c
    assert git_out(sws.target, "rev-parse", "main^{tree}") == \
        git_out(sws.target, "rev-parse", f"{pre}^{{tree}}")
    assert git_out(sws.target, "log", "-1", "--format=%s", "main") == "konstant: roll back ship 1"
    assert git_rc(sws.target, "merge-base", "--is-ancestor", c, "main") == 0          # C6
    assert (sws.target / "README.md").is_file()          # the worktree is the pre-ship tree again
    assert sws.job(jid)["status"] == "verified"         # terminal: the clone's verification held
    fu = sws.job(s["follow_up_id"])
    assert fu["status"] == "queued" and fu["holdout_required"]
    assert README_PROBE in fu["acceptance"] and sws.job(jid)["acceptance"] in fu["acceptance"]
    assert sorted((h["hid"], h["sha256"]) for h in fu["holdouts"]) == \
        sorted((h["hid"], h["sha256"]) for h in sws.job(jid)["holdouts"])
    check = sws.w.run("holdout", "check", fu["id"])
    assert check.returncode == 0, check.stdout + check.stderr       # the copied files hash right
    ev = [e["event"] for e in sws.events()]
    assert "ROLLED_BACK" in ev and "SHIPPED" not in ev


@needs_jail
def test_C5_regression_set_covers_every_job_shipped_so_far(sws):
    j1 = sws.verified_job()
    assert sws.ship(j1).returncode == 0
    j2 = sws.verified_job(scenarios=(H3, H4), module="farewell")
    r = sws.ship(j2, "--json")
    assert r.returncode == 0, r.stderr + r.stdout[-2000:]
    post = sws.ships()[1]["post"]["checks"]
    ran = [c["reason"] for c in post if c["check"] == "regression"]
    assert any(f"of job {j1} passed" in x for x in ran) and any(f"of job {j2} passed" in x
                                                                 for x in ran), ran


@needs_jail
def test_C7_a_target_moved_outside_the_factory_is_a_decision(sws):
    jid = sws.verified_job()
    moved = commit_in(sws.target, "NOTES.md", "someone else's commit\n")
    pre = sws.job(jid)["workdir_base"]
    r = sws.ship(jid)
    assert r.returncode == 1 and f"target moved: expected {pre}" in r.stderr, r.stderr
    assert git_out(sws.target, "rev-parse", "main") == moved and sws.ships() == []
    assert [e["event"] for e in sws.events()] == ["DECISION"]
    assert "target moved" in sws.events()[0]["reason"]


@needs_jail
def test_C10_an_instruction_surface_is_an_owner_decision_then_approved(sws):
    jid = sws.verified_job("ship-extra", FAKE_HARNESS_EXTRA="AGENTS.md",
                           FAKE_HARNESS_EXTRA_TEXT="always ship")
    before = git_out(sws.target, "rev-parse", "main")
    r = sws.ship(jid)
    assert r.returncode == 1 and "DECISION: instruction surface changed (AGENTS.md)" in r.stderr
    assert git_out(sws.target, "rev-parse", "main") == before and sws.ships() == []
    e = sws.events()[-1]
    assert e["event"] == "DECISION" and "instruction surface changed (AGENTS.md)" in e["reason"]
    trail = sws.w.json("job", "show", jid, "--trail")["trail"]
    assert any(t["kind"] == "escalation" and t["actor"] == "factory" for t in trail)
    # the decision is the owner's: the factory identity cannot approve it, the owner can
    assert sws.ship(jid, "--approve-decision", role="factory").returncode == 1
    ok = sws.ship(jid, "--approve-decision", role="owner")
    assert ok.returncode == 0, ok.stderr
    assert git_out(sws.target, "rev-parse", "main") == sws.commit(jid)


@needs_jail
def test_C10b_workflow_import_hook_and_conftest_are_decisions(sws):
    for path in (".github/workflows/release.yml", "sitecustomize.py", "pkg/conftest.py"):
        jid = sws.verified_job("ship-extra", FAKE_HARNESS_EXTRA=path)
        r = sws.ship(jid)
        assert r.returncode == 1 and "DECISION:" in r.stderr and path in r.stderr, r.stderr
    assert sws.ships() == []


@needs_jail
def test_infra_type_is_an_owner_decision_red_and_code_is_not_green(sws):
    jid = sws.verified_job(jtype="infra")
    r = sws.ship(jid)
    assert r.returncode == 1 and "job type infra is an owner decision" in r.stderr, r.stderr
    assert sws.ships() == []
    jid2 = sws.verified_job()                                # green twin: a code job ships
    assert sws.ship(jid2, "--dry-run").returncode == 0
    from konstant.config import DEFAULTS
    assert DEFAULTS["ship"]["decision_types"] == ["infra"]  # Q4: security is not a decision type


@needs_jail
def test_C8_command_target_whose_rollback_fails_halts_all_shipping(tmp_path):
    from tests.ship.conftest import make_ship_ws
    s = make_ship_ws(tmp_path, ship='ship_cmd = "rm README.md"\nrollback_cmd = "false"\n',
                     tail='[factory]\ndefaults = { ship_target = "command" }\n'
                          '[notify]\nkind = "file"\n')
    try:
        jid = s.verified_job()
        r = s.ship(jid)
        assert r.returncode == 4, r.stderr + r.stdout[-1500:]
        assert s.ships()[0]["state"] == "rollback_failed"
        st = s.w.json("factory", "status")
        assert st["shipping"] == "halted"
        log = (s.w.home / "var" / "factory" / "notify.log").read_text()
        assert log.startswith("ROLLBACK_FAILED"), log
        j2 = s.verified_job()            # the command target never moved the branch itself
        r2 = s.ship(j2)
        assert r2.returncode == 1 and "shipping is halted" in r2.stderr
        assert s.w.run("--as", "factory", "factory", "resume-shipping").returncode == 1
        assert s.w.run("--as", "owner", "factory", "resume-shipping").returncode == 0
        assert s.w.json("factory", "status")["shipping"] == "open"
    finally:
        s.w.stop_board()


@needs_jail
def test_forged_object_in_the_clone_is_refused_nothing_ships(sws):
    jid = sws.verified_job()
    clone = sws.w.home / sws.job(jid)["workdir"]
    c = sws.commit(jid)
    blob = git_out(clone, "rev-parse", f"{c}:greeter.py")
    path = clone / ".git" / "objects" / blob[:2] / blob[2:]
    assert path.is_file()
    os.chmod(path, 0o644)
    bad = b'def greet(name="world"):\n    return "BROKEN"\n'
    path.write_bytes(zlib.compress(b"blob %d\0" % len(bad) + bad))       # content != its id
    before = git_out(sws.target, "rev-parse", "main")
    r = sws.ship(jid)
    assert r.returncode == 1 and "does not hash to its id" in r.stderr, r.stderr
    assert git_out(sws.target, "rev-parse", "main") == before and sws.ships() == []


@needs_jail
def test_replace_ref_and_planted_config_in_the_clone_change_nothing_shipped(sws):
    jid = sws.verified_job()
    clone = sws.w.home / sws.job(jid)["workdir"]
    c = sws.commit(jid)
    real = subprocess.run(["git", "-C", str(clone), "cat-file", "blob", f"{c}:greeter.py"],
                          capture_output=True, env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}
                          ).stdout
    broken = subprocess.run(["git", "-C", str(clone), "hash-object", "-w", "--stdin"],
                            input=b'def greet(name="world"):\n    return "BROKEN"\n',
                            capture_output=True).stdout.decode().strip()
    blob = git_out(clone, "rev-parse", f"{c}:greeter.py")
    assert git_rc(clone, "replace", "-f", blob, broken) == 0
    marker = sws.w.src / "fsmonitor-ran"
    with open(clone / ".git" / "config", "a") as fh:
        fh.write(f"[core]\n\tfsmonitor = touch {marker}\n[alias]\n\tst = !touch {marker}\n")
    # red twin: an ordinary git read of the clone sees the replaced object
    seen = subprocess.run(["git", "-C", str(clone), "cat-file", "blob", f"{c}:greeter.py"],
                          capture_output=True).stdout
    assert b"BROKEN" in seen and b"BROKEN" not in real
    r = sws.ship(jid)
    assert r.returncode == 0, r.stderr + r.stdout[-1500:]
    shipped = subprocess.run(["git", "-C", str(sws.target), "cat-file", "blob", "main:greeter.py"],
                             capture_output=True).stdout
    assert shipped == real and (sws.target / "greeter.py").read_bytes() == real
    assert not marker.exists()                       # nothing of the clone's config ran
    assert not Path(sws.target / ".git" / "refs" / "replace").exists()


@needs_jail
def test_a_dirty_target_worktree_is_a_decision_red_then_green(sws):
    jid = sws.verified_job()
    readme = sws.target / "README.md"
    readme.write_text("an edit nobody committed\n")
    before = git_out(sws.target, "rev-parse", "main")
    r = sws.ship(jid)
    assert r.returncode == 1 and "target worktree has local changes (README.md)" in r.stderr
    assert git_out(sws.target, "rev-parse", "main") == before
    assert readme.read_text() == "an edit nobody committed\n"   # konstant overwrote nothing
    assert sws.events()[-1]["event"] == "DECISION"
    readme.write_text("greeter\n")                                # green: clean again
    assert sws.ship(jid).returncode == 0


@needs_jail
def test_apply_target_ships_into_its_dir_and_swaps_back(tmp_path):
    from tests.ship.conftest import make_ship_ws
    s = make_ship_ws(tmp_path, ship='apply_dir = "deployed/greeter"\n',
                     tail='[factory]\ndefaults = { ship_target = "apply" }\n')
    try:
        d = s.w.home / "deployed" / "greeter"
        j1 = s.verified_job()
        r = s.ship(j1)
        assert r.returncode == 0, r.stderr + r.stdout[-1500:]
        assert (d / "README.md").is_file() and "hello {name}" in (d / "greeter.py").read_text()
        j2 = s.verified_job("ship-break")
        r = s.ship(j2)
        assert r.returncode == 3, r.stderr + r.stdout[-1500:]
        assert (d / "README.md").is_file()                   # the previous tree is back
        assert [x["state"] for x in s.ships()] == ["shipped", "rolled_back"]
    finally:
        s.w.stop_board()
