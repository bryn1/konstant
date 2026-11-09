"""The github target (docs/LEVEL5.md 5.1, 5.6 C11 C12; owner decision Q2; wave L5-4) against a
stand-in: a local BARE repository as "GitHub" (its `update` hook logs every ref update and refuses
a non-fast-forward or a delete, as a protected branch does) and the `gh` stand-in on a pinned
path (tests/fixtures/fake_gh.py), which records every pull request create and merge. No network,
no real GitHub."""
from __future__ import annotations

import json

from tests.holdout.conftest import needs_jail
from tests.ship.conftest import H3, H4, commit_in, git_out, git_rc, make_ship_ws


def _no_force(s) -> None:
    pushes = s.pushes()
    assert pushes and all(" ff=yes" in p or " ff=new" in p for p in pushes), pushes


@needs_jail
def test_C11_ship_through_a_pull_request_then_roll_back_through_a_second(gws):
    j1 = gws.verified_job()
    c1, pre = gws.commit(j1), git_out(gws.remote, "rev-parse", "main")
    r = gws.ship(j1, "--json")
    assert r.returncode == 0, r.stderr + r.stdout[-2000:]
    m1 = git_out(gws.remote, "rev-parse", "main")
    assert git_out(gws.remote, "rev-parse", "main^2") == c1 and \
        git_out(gws.remote, "rev-parse", "main^1") == pre          # GitHub's merge commit
    assert git_out(gws.remote, "rev-parse", "main^{tree}") == \
        git_out(gws.remote, "rev-parse", f"{c1}^{{tree}}")
    calls = gws.gh_calls()
    assert [c["call"] for c in calls] == ["pr create", "pr merge"]
    assert calls[0]["head"] == "konstant/ship-1" and calls[0]["sha"] == c1
    assert calls[1]["argv"][calls[1]["argv"].index("--match-head-commit") + 1] == c1
    assert calls[0]["repo"] == "example-org/greeter"
    assert git_out(gws.target, "rev-parse", "main") == m1        # the local target followed
    ship1 = gws.ships()[0]
    assert ship1["state"] == "shipped" and ship1["tip_sha"] == m1
    # a second job, cloned from the shipped state, breaks a post-ship probe: rolled back by PR
    j2 = gws.verified_job("ship-break", scenarios=(H3, H4), module="farewell")
    assert gws.job(j2)["workdir_base"] == m1
    c2 = gws.commit(j2)
    r = gws.ship(j2, "--json")
    assert r.returncode == 3, r.stderr + r.stdout[-2000:]
    s2 = gws.ships()[1]
    assert s2["state"] == "rolled_back"
    assert git_out(gws.remote, "rev-parse", "main^{tree}") == \
        git_out(gws.remote, "rev-parse", f"{m1}^{{tree}}")        # the pre-ship tree again
    assert git_rc(gws.remote, "merge-base", "--is-ancestor", c2, "main") == 0  # history kept
    calls = gws.gh_calls()
    assert [c["call"] for c in calls] == ["pr create", "pr merge"] * 3
    assert calls[4]["head"] == "konstant/rollback-2" and calls[5]["revert"] is True
    rb = git_out(gws.remote, "rev-parse", "main^2")
    assert git_out(gws.remote, "log", "-1", "--format=%s", rb) == "konstant: roll back ship 2"
    _no_force(gws)                                    # every ref update was a fast-forward
    assert git_out(gws.target, "rev-parse", "main") == git_out(gws.remote, "rev-parse", "main")
    assert gws.job(s2["follow_up_id"])["status"] == "queued"


@needs_jail
def test_C12_a_token_shaped_string_is_not_pushed(gws):
    shape = "gh" + "p_" + "Zz9" * 12                       # token-shaped, built at run time
    jid = gws.verified_job("ship-extra", FAKE_HARNESS_EXTRA="settings.py",
                           FAKE_HARNESS_EXTRA_TEXT=f"TOKEN = '{shape}'")
    before = git_out(gws.remote, "for-each-ref", "--format=%(refname) %(objectname)")
    r = gws.ship(jid)
    assert r.returncode == 1 and "DECISION: secret scan finding in settings.py" in r.stderr, \
        r.stderr
    assert shape not in r.stderr + r.stdout
    assert git_out(gws.remote, "for-each-ref", "--format=%(refname) %(objectname)") == before
    assert gws.gh_calls() == [] and gws.pushes() == []
    e = gws.events()[-1]
    assert e["event"] == "DECISION" and "secret scan finding in settings.py" in e["reason"]
    assert shape not in json.dumps(gws.events())


@needs_jail
def test_C12_green_twin_a_clean_diff_is_pushed(gws):
    jid = gws.verified_job("ship-extra", FAKE_HARNESS_EXTRA="settings.py",
                           FAKE_HARNESS_EXTRA_TEXT="GREETING = 'hello'")
    assert gws.ship(jid).returncode == 0
    assert gws.gh_calls() and gws.pushes()


@needs_jail
def test_a_failed_revert_merge_halts_all_shipping(tmp_path):
    s = make_ship_ws(tmp_path, github=True, refuse="rollback-merge",
                     tail='[notify]\nkind = "file"\n')
    try:
        jid = s.verified_job("ship-break")
        r = s.ship(jid)
        assert r.returncode == 4, r.stderr + r.stdout[-1500:]
        assert s.ships()[0]["state"] == "rollback_failed"
        assert s.w.json("factory", "status")["shipping"] == "halted"
        assert (s.w.home / "var" / "factory" / "notify.log").read_text().startswith(
            "ROLLBACK_FAILED")
        _no_force(s)                         # nothing was forced or reset to undo the ship
        j2 = s.verified_job(scenarios=(H3, H4), module="farewell")
        r2 = s.ship(j2)
        assert r2.returncode == 1 and "shipping is halted" in r2.stderr
    finally:
        s.w.stop_board()


@needs_jail
def test_a_merge_the_remote_refuses_leaves_main_unchanged(tmp_path):
    s = make_ship_ws(tmp_path, github=True, refuse="merge")
    try:
        jid = s.verified_job()
        before = git_out(s.remote, "rev-parse", "main")
        r = s.ship(jid)
        assert r.returncode == 1 and "target refused" in r.stderr, r.stderr
        assert git_out(s.remote, "rev-parse", "main") == before
        assert s.ships()[0]["state"] == "failed" and s.events()[-1]["event"] == "DECISION"
    finally:
        s.w.stop_board()


@needs_jail
def test_the_remote_moved_outside_the_factory_is_a_decision(gws):
    jid = gws.verified_job()
    clone = gws.w.src / "elsewhere"
    import subprocess
    subprocess.run(["git", "clone", "-q", str(gws.remote), str(clone)], check=True)
    commit_in(clone, "NOTES.md", "pushed by someone else\n")
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True,
                   capture_output=True)
    moved = git_out(gws.remote, "rev-parse", "main")
    r = gws.ship(jid)
    assert r.returncode == 1 and "target moved: expected" in r.stderr, r.stderr
    assert git_out(gws.remote, "rev-parse", "main") == moved and gws.gh_calls() == []
