"""Every DoD rule of DESIGN §6.4: a planted-bad `test_<rule>_red` beside a `test_<rule>_green`.
A gate that has never failed is not a gate: each red case must name its rule."""
from __future__ import annotations

import time

from konstant.gate import check
from tests.gate.conftest import FakeBoard, done_text, git, old


def test_good_scenario_is_met(scen):
    s = scen().good()
    code, lines, _w, _f = s.check()
    assert code == 0, lines


# --- verdicts ----------------------------------------------------------------------------
def test_verdicts_green(scen):
    assert "verdicts" not in scen().good().rules()


def test_verdicts_red(scen):
    s = scen().good()
    s.write("REVIEW-verdict.md", "ok\n# VERDICT: PASS\nmore text after the verdict\n")
    assert "verdicts" in s.rules()


def test_verdicts_red_two_verdict_lines(scen):
    s = scen().good()
    s.write("TEST-verdict.md", "# VERDICT: FAIL\nnow fixed\n# VERDICT: PASS\n")
    lines = s.check()[1]
    assert any("2 verdict lines" in ln for ln in lines)


def test_verdicts_red_unknown_word_and_malformed_judged(scen):
    s = scen().good()
    s.write("REVIEW-verdict.md", "# JUDGED: not-a-sha\n# VERDICT: LGTM\n")
    lines = "\n".join(s.check()[1])
    assert "unknown verdict word 'LGTM'" in lines and "malformed JUDGED" in lines


def test_verdicts_red_only_stale(scen):
    s = scen()
    s.deliverable()
    for name in ("TEST-verdict.md", "REVIEW-verdict.md", "ARCH-verdict.md"):
        old(s.verdict(name))
    s.done()
    assert any("STALE" in ln for ln in s.check()[1])


# --- phases ------------------------------------------------------------------------------
def test_phases_green(scen):
    assert "phases" not in scen().good().rules()


def test_phases_red(scen):
    s = scen().good()
    (s.out / "REVIEW-verdict.md").unlink()
    code, lines, _w, findings = s.check()
    assert code == 3 and any("no fresh verdict for phase reviewer" in ln for ln in lines)
    assert next(f for f in findings if f.rule == "phases").owner == "verifier:REVIEW-verdict.md"


def test_phases_red_fail_below_cap_goes_to_the_producer(scen):
    s = scen().good()
    s.verdict("TEST-verdict.md", "FAIL")
    f = next(f for f in s.check()[3] if f.rule == "phases")
    assert f.owner == "producer" and "cycle 2 of 3" in f.text


def test_phases_newest_cycle_decides(scen):
    s = scen().good()
    s.verdict("TEST-verdict.md", "FAIL")
    s.verdict("TEST-verdict-c2.md", "PASS")
    assert s.check()[0] == 0


def test_phases_cap_with_blocked_row_is_blocked(scen):
    s = scen().good()
    s.verdict("TEST-verdict-c3.md", "FAIL")
    s.done(done_text("D2 | tests pass | BLOCKED | TEST-verdict-c3.md FAIL after 3 cycles\n"))
    code, lines, _w, _f = s.check()
    assert code == 4 and all(ln.startswith("BLOCKED: ") for ln in lines)


def test_phases_cap_without_blocked_row_is_unmet(scen):
    s = scen().good()
    s.verdict("TEST-verdict-c3.md", "FAIL")
    code, lines, _w, _f = s.check()
    assert code == 3 and any("BLOCKED row" in ln for ln in lines)


def test_phases_read_only_needs_arch_row(scen):
    s = scen(ttype="security")
    s.write("FINDINGS-security.md", "no findings\n")
    s.verdicts()
    s.done(done_text(rows=[]))
    assert any("ARCH | architecture doc" in ln for ln in s.check()[1])
    s.done(done_text(rows=["ARCH | architecture doc matches reality | N/A | this run changed no "
                           "project file"]))
    assert s.check()[0] == 0


# --- judged ------------------------------------------------------------------------------
def test_judged_green(scen):
    assert "judged" not in scen(use_git=True).good().rules()


def test_judged_red(scen):
    s = scen().good()
    s.write("greet.py", 'def greet():\n    return "HELLO"\n', s.project)   # edited after judging
    lines = s.check()[1]
    assert any("changed since - proj/greet.py" in ln for ln in lines)


def test_judged_red_git_project_edit(scen):
    s = scen(use_git=True).good()
    s.write("greet.py", 'def greet():\n    return "x"\n', s.project)
    assert any("changed since - git/greet.py" in ln for ln in s.check()[1])


def test_judged_touch_changes_nothing(scen):
    s = scen().good()
    old(s.project / "greet.py", 10)
    assert s.check()[0] == 0


def test_judged_red_missing_line(scen):
    s = scen().good()
    s.verdict("ARCH-verdict.md", judged_line=False)
    assert any("no single '# JUDGED: <sha>' line" in ln for ln in s.check()[1])


def test_judged_red_pin_args_unrecorded(scen):
    s = scen().good()
    for f in (s.out / ".tmp" / "judged").glob("*.args.json"):
        f.unlink()
    assert any(ln.startswith("PIN-ARGS-UNRECORDED") for ln in s.check()[1])


def test_judged_red_pin_base_differs(scen):
    s = scen(use_git=True).good()
    s.rec["git_base"] = git(s.project, "rev-parse", "HEAD").stdout.strip()   # moved base
    s.save()
    assert any(ln.startswith("PIN-BASE-DIFFERS") for ln in s.check()[1])


def test_judge_refuses_an_empty_state(scen):
    from konstant.gate.rules import judged
    import pytest
    s = scen()
    with pytest.raises(judged.JudgeRefused, match="EMPTY"):
        judged.judge(s.rec)


# --- done --------------------------------------------------------------------------------
def test_done_green(scen):
    assert "done" not in scen().good().rules()


def test_done_red(scen):
    s = scen().good()
    (s.out / "DONE.md").unlink()
    assert any(ln.startswith("DONE.md missing") for ln in s.check()[1])


def test_done_red_rows(scen):
    s = scen().good()
    s.done(done_text("D2 | docs updated | FAIL | not yet\nD3 | api works | PASS | ok\n"
                     "D4 | perf | N/A | -\nD5 | x | PASS\nD6 | a | b | PASS | moved\n"))
    text = "\n".join(s.check()[1])
    for needle in ("D2 is FAIL", "placeholder evidence 'ok'", "D4 is N/A with no reason",
                   "D5 is PASS with no evidence", "is in cell 4, not the 3rd"):
        assert needle in text, needle


def test_done_red_stale_and_no_pass(scen):
    s = scen().good()
    s.done("ID | claim | STATUS | evidence\nD1 | x | N/A | not asked\nCLEANUP: NONE-NEEDED\n")
    assert any("no PASS row" in ln for ln in s.check()[1])
    old(s.out / "DONE.md")
    assert any("STALE" in ln for ln in s.check()[1])


# --- absence / surfaces (build types) -----------------------------------------------------
def test_absence_green(scen):
    assert "absence" not in scen().good().rules()


def test_absence_red(scen):
    s = scen().good()
    s.done(done_text().replace("N1 | proof of absence | N/A | a pure function has no forbidden "
                               "path\n", ""))
    assert "absence" in s.rules()


def test_absence_not_asked_of_doc_types(scen):
    s = scen(ttype="docs")
    s.write("guide.md", "how to use greet\n")
    s.verdicts()
    s.done("ID | claim | STATUS | evidence\nD1 | guide written | PASS | guide.md\nCLEANUP: NONE-NEEDED\n")
    assert s.check()[0] == 0


def test_surfaces_green(scen):
    assert "surfaces" not in scen().good().rules()


def test_surfaces_red(scen):
    s = scen().good()
    s.done(done_text(rows=["S1 | surface backend | PASS | greet.py"]))
    assert any("lacks surface row(s) db, frontend" in ln for ln in s.check()[1])


# --- cleanup -----------------------------------------------------------------------------
def test_cleanup_green(scen):
    assert "cleanup" not in scen(gate={"cleanup": "fail"}).good().rules()


def test_cleanup_red(scen):
    s = scen(gate={"cleanup": "fail"}).good()
    s.done(done_text(cleanup=False))
    assert "cleanup" in s.rules(severity="unmet")


def test_cleanup_warn_mode_never_refuses(scen):
    s = scen().good()
    s.done(done_text(cleanup=False))
    code, _l, warns, _f = s.check()
    assert code == 0 and any("CLEANUP" in w for w in warns)


# --- tests / exercise --------------------------------------------------------------------
def test_tests_green(scen):
    assert "tests" not in scen().good().rules()


def test_tests_red(scen):
    s = scen().good()
    s.write("test_more.py", "def test_broken():\n    assert 1 == 2\n")
    s.verdicts()
    assert any(ln.startswith("pytest failed in") for ln in s.check()[1])


def test_tests_red_configured_command(scen):
    s = scen(gate={"test_cmd": "python3 -c 'import sys; sys.exit(3)'"}).good()
    assert any("exit 3" in ln for ln in s.check()[1])


def test_exercise_green(scen):
    s = scen().good()
    s.write("helper.py", "def shout(x):\n    return x.upper()\n")
    s.write("test_helper.py", "import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\n"
                              "from helper import shout\n\n\ndef test_shout():\n"
                              "    assert shout('a') == 'A'\n")
    s.verdicts()
    assert "exercise" not in s.rules()


def test_exercise_red(scen):
    s = scen().good()
    s.write("helper.py", "def shout(x):\n    return x.upper()\n")
    s.verdicts()
    assert any("never call into helper.py" in ln for ln in s.check()[1])


# --- lastmile ----------------------------------------------------------------------------
def test_lastmile_green(scen):
    assert "lastmile" not in scen(use_git=True).good().rules()


def test_lastmile_red(scen):
    s = scen(use_git=True).good()
    s.write("notes.txt", "left behind\n", s.project)
    s.verdicts()
    assert any("untracked file(s) created during the run" in ln for ln in s.check()[1])


def test_lastmile_red_marker_word(scen):
    s = scen(use_git=True)
    s.write("greet.py", "def greet():\n    return 'hello'  # " + "TO" + "DO: i18n\n", s.project)
    s.commit("greet.py")
    s.write("test_greet.py", "def test_x():\n    assert True\n")
    s.verdicts()
    s.done()
    assert any("marker words added" in ln for ln in s.check()[1])


def test_lastmile_red_changed_test_fails(scen):
    s = scen(use_git=True).good()
    s.write("test_core.py", "def test_core():\n    assert False\n", s.project)
    s.commit("test_core.py")
    s.verdicts()
    assert any("changed test file(s) fail" in ln for ln in s.check()[1])


# --- hygiene -----------------------------------------------------------------------------
def test_hygiene_green(scen):
    s = scen().good()
    s.write("big.py", "# reason: one generated table\n" + "X = 1\n" * 450)
    s.verdicts()
    assert "hygiene" not in s.rules()


def test_hygiene_red(scen):
    s = scen().good()
    s.write("big.py", "X = 1\n" * 401)
    s.verdicts()
    assert any("big.py is 401 lines" in ln for ln in s.check()[1])


def test_hygiene_red_project_file_grew(scen):
    s = scen(use_git=True)
    s.write("core.py", "X = 1\n" * 500, s.project)
    s.commit("core.py")
    s.rec["git_base"] = git(s.project, "rev-parse", "HEAD").stdout.strip()
    s.save()
    s.write("core.py", "X = 1\n" * 650, s.project)
    s.commit("core.py")
    s.good()
    assert any("core.py grew to 650 lines (was 500" in ln for ln in s.check()[1])


def test_hygiene_grandfathers_a_file_that_did_not_grow(scen):
    s = scen(use_git=True)
    s.write("core.py", "X = 1\n" * 700, s.project)
    s.commit("core.py")
    s.rec["git_base"] = git(s.project, "rev-parse", "HEAD").stdout.strip()
    s.save()
    s.write("core.py", "X = 2\n" * 700, s.project)
    s.commit("core.py")
    s.good()
    assert "hygiene" not in s.rules()


# --- verified ----------------------------------------------------------------------------
def _job(status, *verdicts):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 1))
    return {"id": 7, "status": status,
            "verifications": [{"id": i, "round": i, "verdict": v, "finished_at": now}
                              for i, v in enumerate(verdicts, 1)]}


def test_verified_green(scen):
    s = scen(job=7).good()
    assert "verified" not in s.rules(FakeBoard({7: _job("verified", "PASS")}))
    assert "verified" not in s.rules(FakeBoard({7: _job("claimed")}))   # not closed yet


def test_verified_red(scen):
    s = scen(job=7).good()
    assert any("has no konstant verify verdict" in ln
               for ln in s.check(FakeBoard({7: _job("completed_unverified")}))[1])


def test_verified_red_fail_and_blocked(scen):
    s = scen(job=7).good()
    assert "verified" in s.rules(FakeBoard({7: _job("queued", "FAIL")}), severity="unmet")
    code, lines, _w, _f = s.check(FakeBoard({7: _job("completed_unverified", "BLOCKED")}))
    assert code == 4 and any("BLOCKED" in ln for ln in lines)


def test_verified_red_board_unreachable_fails_closed(scen):
    s = scen(job=7).good()
    assert "verified" in s.rules(FakeBoard(down=True), severity="unmet")
    assert s.check(offline=True)[0] == 0          # --offline skips it, with a warning


# --- authorship --------------------------------------------------------------------------
def _runner_manifests(s, forged=False):
    s.manifest("01-1-architect-c1", 1, "architect")
    s.manifest("02-2-coder-c1", 2, "coder",
               created=["test_greet.py"] + (["TEST-verdict.md"] if forged else []))
    s.manifest("03-3-tester-c1", 3, "tester", verdict="TEST-verdict.md",
               created=[] if forged else ["TEST-verdict.md"], modified=["TEST-verdict.md"] if forged else [],
               group_verdicts=["TEST-verdict.md", "REVIEW-verdict.md"])
    s.manifest("03-4-reviewer-c1", 4, "reviewer", verdict="REVIEW-verdict.md",
               created=["REVIEW-verdict.md"] + ([] if forged else ["TEST-verdict.md"]),
               group_verdicts=["TEST-verdict.md", "REVIEW-verdict.md"])
    s.manifest("04-5-architect-c1", 5, "architect", verdict="ARCH-verdict.md",
               created=["ARCH-verdict.md"])


def test_authorship_green(scen):
    s = scen(mode="runner").good()
    _runner_manifests(s)
    assert "authorship" not in s.rules()


def test_authorship_red(scen):
    s = scen(mode="runner").good()
    _runner_manifests(s, forged=True)
    lines = s.check()[1]
    assert any(ln.startswith("AUTHORSHIP: TEST-verdict.md") and "2-coder" in ln for ln in lines)


def test_authorship_red_written_outside_any_phase(scen):
    s = scen(mode="runner").good()
    _runner_manifests(s)
    s.verdict("REVIEW-verdict-c2.md")
    assert any(ln.startswith("AUTHORSHIP: REVIEW-verdict-c2.md was not created")
               for ln in s.check()[1])


def test_authorship_interactive_is_a_warning(scen):
    code, _l, warns, _f = scen().good().check()
    assert code == 0 and any(w.startswith("AUTHORSHIP WARNING") for w in warns)


# --- the check itself --------------------------------------------------------------------
def test_a_crashed_rule_is_a_check_error_never_met(scen, monkeypatch):
    s = scen().good()

    def boom(run):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(check, "RULES", check.RULES + (("boom", boom),))
    code, lines, _w, _f = s.check()
    assert code == 5 and lines[0].startswith("CHECK-ERROR")


def test_usage_error_on_a_dir_without_a_record(tmp_path):
    assert check.run_check(tmp_path)[0] == 2
