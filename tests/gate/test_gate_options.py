"""The v0.2.x gate options and the licence scratch-venv exclusion: the rules split out of
tests/gate/test_rules.py when that file passed the 600-line test limit (file hygiene,
tests/unit/test_file_hygiene.py): [gate] test_project, [gate] done_only_max_resumes and
the common.out_files walk that skips .tmp-* scratch dirs."""
from __future__ import annotations


# --- test_project gate option (v0.2.0) ------------------------------------------

def _project_tests_run(tmp_path, test_project: bool):
    """A Run whose project holds a failing test file and OUT has no tests."""
    from konstant.gate.rules.common import Run
    out = tmp_path / "out"
    out.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_bad.py").write_text("import nonexistent_xyz_module\ndef test_x(): pass\n")
    rec = {"out": str(out), "project": str(project),
           "gate": {"jail": False, "test_cmd": "auto", "test_project": test_project}}
    return Run(run_dir=tmp_path, rec=rec)


def test_test_project_true_runs_project_pytest(tmp_path):
    """Default behaviour: project-level pytest runs and reports failures."""
    from konstant.gate.rules import tests as tests_rule
    run = _project_tests_run(tmp_path, test_project=True)
    found = tests_rule.check(run)
    assert found, "expected a finding when project pytest fails"
    assert any("project" in f.text for f in found)


def test_test_project_false_skips_project_pytest(tmp_path):
    """[gate] test_project = false: project-level pytest is never run, no finding produced."""
    from konstant.gate.rules import tests as tests_rule
    run = _project_tests_run(tmp_path, test_project=False)
    found = tests_rule.check(run)
    assert not found, f"expected no findings when test_project=false, got: {found}"


# --- done_only_max_resumes gate option (v0.2.0) ----------------------------------

def test_done_only_max_resumes_stops_early_on_cosmetic_findings(tmp_path):
    """When every unmet finding is from a non-UNEXCUSABLE rule and resumes >= cap, stop.

    Sequence with done_only_max_resumes=1:
      call 1 → resumes=0, 0>=1? No → phase runs; resumes becomes 1
      call 2 → resumes=1, 1>=1? Yes → STOP UNMET
    Total: 2 check calls, code=UNMET.
    Each call uses a unique message so the 'repeated reason' guard does not fire first.
    """
    from unittest.mock import patch, MagicMock
    from konstant.gate import loop, check as check_mod
    from konstant.gate.rules.common import Finding

    pr = MagicMock()
    pr.rec = {"gate": {"done_only_max_resumes": 1}, "run_dir": str(tmp_path), "out": str(tmp_path)}
    pr.run_dir = tmp_path

    calls = []

    def fake_check(*a, **kw):
        n = len(calls) + 1
        calls.append(n)
        f = Finding("done", f"DONE.md missing (call {n})", owner="producer")
        return check_mod.UNMET, [f"[done] DONE.md missing (call {n})"], [], [f]

    with patch.object(check_mod, "run_check", fake_check):
        code, _ = loop.dod_loop(pr, None, max_resumes=3, err=lambda m: None)

    assert code == check_mod.UNMET, "should stop at UNMET after cap reached"
    assert len(calls) == 2, (
        f"expected 2 check calls (resumes=0 → phase → resumes=1 → cap hits), got {len(calls)}")


def test_done_only_max_resumes_not_applied_when_unexcusable(tmp_path):
    """When an UNEXCUSABLE finding is present, done_only_max_resumes is ignored.

    Sequence with done_only_max_resumes=0 and an UNEXCUSABLE finding on calls 1-2:
      call 1 → UNEXCUSABLE → cap check skipped → phase runs; resumes becomes 1
      call 2 → UNEXCUSABLE → cap check skipped → phase runs; resumes becomes 2
      call 3 → MET → return MET
    Total: 3 check calls, code=MET.
    """
    from unittest.mock import patch, MagicMock
    from konstant.gate import loop, check as check_mod
    from konstant.gate.rules.common import Finding

    pr = MagicMock()
    pr.rec = {"gate": {"done_only_max_resumes": 0}, "run_dir": str(tmp_path), "out": str(tmp_path)}
    pr.run_dir = tmp_path

    calls = []

    def fake_check(*a, **kw):
        n = len(calls) + 1
        calls.append(n)
        if n <= 2:
            f = Finding("tests", f"pytest failed (call {n})", owner="producer")
            return check_mod.UNMET, [f"[tests] pytest failed (call {n})"], [], [f]
        return check_mod.MET, [], [], []

    with patch.object(check_mod, "run_check", fake_check):
        code, _ = loop.dod_loop(pr, None, max_resumes=3, err=lambda m: None)

    assert code == check_mod.MET, "unexcusable finding should not be gated by done_only_max_resumes"
    assert len(calls) == 3, f"expected 3 check calls (2 UNMET + 1 MET), got {len(calls)}"


# --- licence: .tmp-* scratch venv exclusion ------------------------------------------------

def test_licence_out_files_skips_tmp_scratch_dirs(tmp_path):
    """out_files must not walk into .tmp-<name> scratch dirs (e.g. jail venvs).

    A Python file inside OUT/.tmp-venv/lib/site-packages/ must not appear in the
    licence rule's changed() output — it is a dependency, not agent-written code.
    If it did appear, every dependency with an SPDX header would generate a spurious
    LICENCE finding.  The companion test below checks that files outside .tmp-* still
    appear (the exclusion is not a no-op).
    """
    from konstant.gate.rules.common import out_files
    out = tmp_path / "OUT"
    # a real output file (should be yielded)
    real = out / "solution.py"
    real.parent.mkdir(parents=True)
    real.write_text("# SPDX-License-Identifier: MIT\n")
    # a file inside a .tmp-venv scratch dir (must be skipped)
    scratch = out / ".tmp-venv" / "lib" / "site-packages" / "erfa" / "core.py"
    scratch.parent.mkdir(parents=True)
    scratch.write_text("# SPDX-License-Identifier: BSD-3-Clause\n")
    # a file inside a plain .tmp dir (already in RUN_DIRS, must also be skipped)
    tmp_file = out / ".tmp" / "work.py"
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("temp\n")

    found = [str(f) for f in out_files(out)]
    assert any("solution.py" in f for f in found), "real output file must be yielded"
    assert not any(".tmp-venv" in f for f in found), ".tmp-venv must be excluded"
    assert not any(".tmp" + "/" in f or ".tmp" + "\\" in f for f in found), ".tmp must be excluded"


def test_licence_out_files_skips_multiple_tmp_scratch_dirs(tmp_path):
    """out_files skips all .tmp-<name> patterns, not just one known name."""
    from konstant.gate.rules.common import out_files
    out = tmp_path / "OUT"
    real = out / "patch.py"
    real.parent.mkdir(parents=True)
    real.write_text("fixed = True\n")
    for name in (".tmp-astropy", ".tmp-envs", ".tmp-build"):
        d = out / name / "sub"
        d.mkdir(parents=True)
        (d / "pkg.py").write_text("code\n")

    found = [str(f) for f in out_files(out)]
    assert any("patch.py" in f for f in found)
    for name in (".tmp-astropy", ".tmp-envs", ".tmp-build"):
        assert not any(name in f for f in found), f"{name} must be excluded"
