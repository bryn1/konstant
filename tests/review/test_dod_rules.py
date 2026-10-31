"""DoD-check findings at check level: F-01 (DECLINED), F-05 (verdict changed after its phase),
F-06/F-11 (forged records), F-09 (header heuristic), F-18 (project tests), F-21 (DONE vs DoD)."""
from __future__ import annotations

import hashlib
import json
import sys

from konstant.gate import check
from konstant.gate.rules.common import git_head
from tests.gate.conftest import FakeBoard, done_text

FAILING_TEST = ("import sys\nsys.path.insert(0, {p!r})\nfrom greet import greet\n\n\n"
                "def test_greet():\n    assert greet() == 'hello world'\n")
QUOTED = ['DECLINED | pytest failed in the out directory | "the owner accepted the failing test '
          'today"',
          'DECLINED | ends verdict FAIL from the tester | "the owner said this is acceptable for '
          'now"']


def _failed_run(s):
    """REVIEW F-01: the tester's capped cycle says FAIL and the OUT test fails."""
    s.deliverable()
    s.write("test_greet.py", FAILING_TEST.format(p=str(s.project)))
    s.verdicts()
    s.verdict("TEST-verdict-c3.md", "FAIL")
    return s


def test_F01_invented_owner_quote_excuses_nothing(scen):
    s = _failed_run(scen())
    s.done(done_text("\n".join(QUOTED) + "\n"))
    code, lines, _w, _f = s.check()
    assert code == check.UNMET, lines
    text = "\n".join(lines)
    assert "pytest failed" in text and "VERDICT: FAIL" in text


def test_F01_any_existing_job_is_not_an_owner_ruling(scen):
    s = _failed_run(scen())
    s.done(done_text("DECLINED | pytest failed in the out directory | job 1\n"
                     "DECLINED | ends verdict FAIL from the tester | job 1\n"))
    board = FakeBoard({1: {"id": 1, "status": "queued", "trail": []}})
    assert s.check(board=board)[0] == check.UNMET


def _fail_row_run(s, trail):
    s.good()
    s.done(done_text(extra="DECLINED | token refresh returns 500 | job 7\n",
                     rows=["D2 | the token refresh works | FAIL | token refresh returns 500"]
                     + [f"S{i} | surface {x} | N/A | not touched" for i, x in enumerate(
                         ["backend", "db", "frontend", "api contract", "tests", "docs",
                          "deploy"], 1)]))
    return s.check(board=FakeBoard({7: {"id": 7, "status": "claimed", "trail": trail}}))


def test_F01_owner_note_on_the_board_excuses_an_excusable_finding(scen):
    owner = [{"role": "owner", "kind": "note", "actor": "owner",
              "body": "DECLINED: token refresh returns 500"}]
    assert _fail_row_run(scen(), owner)[0] == check.MET


def test_F01_a_non_owner_note_resolves_nothing(scen):
    worker = [{"role": "orchestrator", "kind": "note", "actor": "orchestrator",
               "body": "DECLINED: token refresh returns 500"}]
    code, lines, _w, _f = _fail_row_run(scen(), worker)
    assert code == check.UNMET and any("D2 is FAIL" in ln for ln in lines), lines


def test_F05_verdict_changed_after_its_phase_ended_is_authorship(scen):
    s = scen(mode="runner").good()
    for n, (label, agent, vf) in enumerate([("03-3-tester-c1", "tester", "TEST-verdict.md"),
                                            ("04-4-reviewer-c1", "reviewer", "REVIEW-verdict.md"),
                                            ("05-5-architect-c1", "architect", "ARCH-verdict.md")]):
        sha = hashlib.sha256((s.out / vf).read_bytes()).hexdigest()
        s.manifest(label, n + 3, agent, verdict=vf, created=[vf], shas={vf: sha})
    assert s.check()[0] == check.MET
    v = s.out / "TEST-verdict.md"
    v.write_text(v.read_text().replace("findings: checked", "findings: rewritten later"))
    code, lines, _w, _f = s.check()
    assert code == check.UNMET and any(ln.startswith("AUTHORSHIP:") and "TEST-verdict.md" in ln
                                       for ln in lines), lines


def _forged(where, marker, mode="interactive"):
    out = where / "out"
    out.mkdir(parents=True)
    (out / "X-verdict.md").write_text("ok\n# VERDICT: PASS\n")
    (out / "DONE.md").write_text("ID | claim | STATUS | evidence\nD1 | it works | PASS | "
                                 "curl said 200 OK\nCLEANUP: NONE-NEEDED\n")
    cmd = f"{sys.executable} -c \"open({str(marker)!r}, 'w').write('pwned')\""
    rec = {"type": "code", "out": str(out), "phases": [], "mode": mode, "start": 1,
           "gate": {"test_cmd": cmd},
           "verdict_words": {"pass": ["PASS"], "fail": ["FAIL"], "blocked": ["BLOCKED"]}}
    (where / "record.json").write_text(json.dumps(rec))
    return where


def test_F06_record_test_cmd_is_never_executed(tmp_path, monkeypatch):
    try:                                   # the config source alone is tested, never the jail
        from konstant import jail
        monkeypatch.setattr(jail, "available", lambda: False)
    except ImportError:                    # the reviewed code had no jail
        pass
    (tmp_path / "ws" / "var" / "runs").mkdir(parents=True)
    marker = tmp_path / "PWNED-check"
    run = _forged(tmp_path / "ws" / "var" / "runs" / "fake", marker)
    check.run_check(run)
    assert not marker.exists(), "task check executed the record's test_cmd"
    assert check.load_run(run).gate["test_cmd"] == "auto"


def test_F11_a_run_dir_outside_var_runs_is_refused(tmp_path):
    run = _forged(tmp_path / "projects" / "demo" / ".audits" / "fake", tmp_path / "m")
    code, _l, err, _f = check.run_check(run)
    assert code == check.USAGE and "var/runs" in " ".join(err)


def test_F11_record_phases_are_rederived_from_the_catalog(tmp_path):
    run = _forged(tmp_path / "ws" / "var" / "runs" / "fake", tmp_path / "m")
    code, lines, _w, _f = check.run_check(run)
    assert code == check.UNMET and any("TEST-verdict.md" in ln for ln in lines), lines


def test_F09_a_status_cell_does_not_hide_a_fail_row(scen):
    s = scen().good()
    s.done(done_text(rows=["D2 | the token refresh works | FAIL | refresh returns 500 | status",
                           "D3 | Status | UNVERIFIED | not checked"]
                     + [f"S{i} | surface {x} | N/A | not touched" for i, x in enumerate(
                         ["backend", "db", "frontend", "api contract", "tests", "docs",
                          "deploy"], 1)]))
    code, lines, _w, _f = s.check()
    assert code == check.UNMET
    assert any("D2 is FAIL" in ln for ln in lines) and any("D3 is UNVERIFIED" in ln
                                                           for ln in lines), lines


def test_F18_the_project_test_suite_runs(scen):
    s = scen(use_git=True)
    s.write("tests/test_existing.py", "def test_existing():\n    assert 1 + 1 == 3\n", s.project)
    s.commit("tests/test_existing.py")
    s.rec["git_base"] = git_head(str(s.project))
    s.save()
    s.good()
    code, lines, _w, _f = s.check()
    assert code == check.UNMET and any("test_existing" in ln for ln in lines), lines


def _dod_job(s, done_rows):
    s.rec["job"] = 5
    s.rec["acceptance"] = "DoD: greet returns hello\n- the README documents greet"
    s.save()
    s.good()
    s.done(done_text(rows=done_rows + [f"S{i} | surface {x} | N/A | not touched" for i, x in
                                       enumerate(["backend", "db", "frontend", "api contract",
                                                  "tests", "docs", "deploy"], 1)]))
    return s.check(offline=True)


def test_F21_every_dod_row_needs_its_done_row(scen):
    code, lines, _w, _f = _dod_job(scen(), [])
    assert code == check.UNMET and any("DoD-2" in ln for ln in lines), lines


def test_F21_dod_rows_present_is_met(scen):
    rows = ["DoD-1 | greet returns hello | PASS | pytest -q: 1 passed",
            "DoD-2 | the README documents greet | PASS | grep -c greet README.md -> 1"]
    code, lines, _w, _f = _dod_job(scen(), rows)
    assert code == check.MET, lines


def test_F21_a_dod_row_cannot_be_na(scen):
    rows = ["DoD-1 | greet returns hello | PASS | pytest -q: 1 passed",
            "DoD-2 | the README documents greet | N/A | not needed"]
    code, lines, _w, _f = _dod_job(scen(), rows)
    assert code == check.UNMET and any("DoD-2" in ln for ln in lines), lines
