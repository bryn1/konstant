"""The evidence contract on close: the vacuity corpus both ways, the negative control, the
self-attested classification, and the API refusals with their policy modes.

The corpus is the calibration and has TWO halves on purpose: a gate tested only on what it should
catch is half-tested, and a vacuity rule that refuses honest output is worse than no rule.
"""
from __future__ import annotations

import pytest

from konstant.board import evidence as ev
from tests.board.conftest import GOOD_EVIDENCE

# A real-shaped canary transcript that QUOTES a planted vacuous input while reporting real counts
# in shapes outside the classic noun list ("8 distinct sha256s", "12 siblings", "x14", "17 probe
# jobs"). It needs BOTH the quoted-input exemption and the widened counter-evidence.
CANARY_TRANSCRIPT = (
    "CANARY PASSED -- every leg executed, codes captured, the positive leg re-run independently.\n"
    "P1: each worker pinned to its own wrapper; the bare client is dead for workers.\n"
    "P2 tokens: PER-ROLE (8 distinct sha256s), so closer != verifier holds by identity.\n"
    "POSITIVE: child filed by the orchestrator, claimed by the worker (exit 0).\n"
    "NEGATIVE#1 as the closer: status=verified -> 403 (verifier role); complete {} -> 400 "
    "(evidence required); complete verify_output='Ran 0 tests' -> 400 (cannot-fail door).\n"
    "NEGATIVE#2: 12 siblings filed in one batch -> 'FILED and NOT RELEASED' x14, ZERO dispatched.\n"
    "17 probe jobs cancelled with reason; workspace residue removed.\n"
)

VACUOUS_OUTPUTS = [
    ("unittest discover over an empty tree",
     "\n------------------------------------------------\nRan 0 tests in 0.000s\n\nOK"),
    ("pytest with everything deselected", "no tests ran in 0.01s"),
    ("pytest collecting nothing", "collected 0 items\n\nno tests ran in 0.02s"),
    ("jest with no test files", "No tests found, exiting with code 0"),
    ("rspec on an empty suite", "0 examples, 0 failures\n\nFinished in 0.0002 seconds"),
    ("pytest where everything skipped", "0 passed, 3 skipped in 0.11s"),
    ("mocha on an empty suite", "  0 passing (2ms)"),
    ("go test on a package with no tests", "?   example.com/pkg  [no test files]\nok"),
    ("a scanner handed no files", "scanned 0 files for secrets\nclean"),
    ("the same, in the other word order", "secret scan complete: 0 files checked"),
    ("shellcheck invoked with no arguments",
     "No files specified.\nUsage: shellcheck [OPTIONS...] FILES..."),
    ("a linter whose glob matched nothing", "no python files to check"),
    ("a home-made gate with an empty worklist", "nothing to verify\ndone"),
    ("a runner that asserted nothing", "0 assertions, 0 failures\nBuild OK"),
]

LEGITIMATE_OUTPUTS = [
    ("pytest, an ordinary pass", "12 passed in 0.34s"),
    ("pytest, a big run with skips", "100 passed, 2 skipped in 12.01s"),
    ("unittest, ten tests", "..........\n----------\nRan 10 tests in 0.012s\n\nOK"),
    ("unittest, exactly one test", ".\n----------\nRan 1 test in 0.000s\n\nOK"),
    ("unittest with skips", "OK (skipped=3)"),
    ("mocha, an ordinary pass", "  12 passing (340ms)"),
    ("go test, an ordinary pass", "ok      example.com/pkg  0.012s"),
    ("mypy on a clean tree", "Success: no issues found in 42 source files"),
    ("black on a formatted tree", "All done!\n1 file left unchanged."),
    ("a secret scan that read files", "gitleaks: no leaks found\nscanned 143 files in 0.8s"),
    ("zero DEFECTS", "0 errors, 0 warnings"),
    ("a summary saying nothing broke", "40 tests, 0 tests failed"),
    ("npm audit on a clean lockfile", "found 0 vulnerabilities"),
    ("a query asserting no orphan rows", " id \n----\n(0 rows)"),
    ("a grep-based scan of an artefact", "no matches found in build/release.tar"),
    ("no temp files left behind", "no files matched *.tmp"),
    ("git, a re-apply changed nothing", "nothing to commit, working tree clean"),
    ("git diff --stat, idempotent apply", "0 files changed, 0 insertions(+), 0 deletions(-)"),
    ("a deploy assertion", "Deployed. 4 services healthy, 0 failed."),
    ("a coverage summary", "TOTAL   210    0   100%"),
    ("a row-count assertion", "row_count=1841"),
    ("a checker naming what it inspected", "checked 23 files, 0 problems"),
    ("a migration with nothing left", "alembic: no new migrations, head is 8f3c2a1"),
    ("a lint pass over real files", "ruff: checked 88 files, all clean"),
    ("a note about test files, in prose", "regenerated 4 test files"),
    ("a long build log with one empty sub-run",
     "building 40 packages\ntests/legacy: no tests ran\ntests/core: ok\n312 passed in 41.20s"),
    ("a multi-package run, one package empty",
     "pkg a: 18 tests passed\npkg b: collected 0 items\npkg c: ok"),
    ("dotnet, a passing 68-test run, key-bound zero",
     "BUILD_RC=0 TEST_RC=0 Build succeeded. Passed! Failed:0 Passed:68"),
    ("dotnet, the spaced variant", "Test Run Successful.\nFailed: 0 Passed: 68 Skipped: 0"),
    ("a suite counted the other way round", "Result: **38 tests, 0 failures, 0 errors, 0.011s**"),
    ("an MSBuild tail", "    0 Warning(s)\n    0 Error(s)"),
    ("a grep -c asserting an append-only file",
     "grep -cE 'DELETE FROM|UPDATE items SET' archive.py -> **0** matches (append-only)."),
    ("a restart-count assertion", "all active, NRestarts=0, 0 new-process errors"),
    ("a leak assertion", "asserts no leak from retrieve(); 6 passed in 0.9s"),
    ("a job about this rule, quoting the phrase",
     "3.10   286 passed   44/44 mutants\n"
     "- the output says 'Ran 0 tests', and nothing else in it reports a non-zero count"),
    ("a canary quoting its own planted vacuous input", CANARY_TRANSCRIPT),
]


@pytest.mark.parametrize("name,output", VACUOUS_OUTPUTS, ids=[n for n, _ in VACUOUS_OUTPUTS])
def test_output_that_measured_nothing_is_vacuous(name, output):
    assert ev.vacuity_problem(output), f"{name!r} measured nothing and was let through"


@pytest.mark.parametrize("name,output", LEGITIMATE_OUTPUTS, ids=[n for n, _ in LEGITIMATE_OUTPUTS])
def test_real_passing_output_is_never_called_vacuous(name, output):
    assert ev.vacuity_problem(output) is None, f"{name!r} is real evidence and was refused"


def test_the_line_is_zero_subjects_not_zero_defects():
    for nothing in ("0 tests ran", "Ran 0 tests in 0.001s", "collected 0 items",
                    "0 passed, 3 skipped in 0.11s", "no tests found"):
        assert ev.vacuity_problem(nothing), nothing
    for clean in ("0 tests failed", "0 failures", "0 errors", "0 leaks found", "(0 rows)",
                  "no matches", "nothing to commit", "no files matched *.tmp",
                  "0 vulnerabilities found"):
        assert ev.vacuity_problem(clean) is None, clean


def test_counter_evidence_stands_a_needle_down():
    text = "tests/legacy: no tests ran\ntests/core ok\n312 passed in 41.20s"
    assert ev.first_vacuity_needle(text)
    assert ev.measured_something(text) == "312 passed"
    assert ev.vacuity_problem(text) is None


def test_counter_evidence_reads_counts_in_both_word_orders():
    assert ev.measured_something("Passed: 68") == "Passed: 68"
    assert ev.measured_something("Total=41") == "Total=41"
    assert ev.measured_something("tests: 12") == "tests: 12"
    assert ev.measured_something("Passed: 0") is None


def test_a_key_bound_zero_is_not_a_count_of_the_next_noun():
    assert ev.first_vacuity_needle("Failed:0 Passed:68") is None
    assert ev.first_vacuity_needle("failures=0 passed=68") is None
    spaced = "Failed: 0 Passed: 68"
    assert ev.first_vacuity_needle(spaced) is not None and ev.vacuity_problem(spaced) is None
    assert ev.vacuity_problem("secret scan complete: 0 files checked") is not None


def test_some_legitimate_outputs_come_near_the_lexicon():
    near = [n for n, t in LEGITIMATE_OUTPUTS if ev.first_vacuity_needle(t)]
    assert near, "the corpus does not test where the line falls"


def test_non_string_output_is_ignored():
    for junk in (None, 12, [], {}, True):
        assert ev.vacuity_problem(junk) is None and ev.measured_something(junk) is None


def test_quoted_needle_is_a_test_input_not_a_result():
    text = "NEGATIVE#1: complete verify_output='Ran 0 tests' -> 400 (cannot-fail door)."
    assert ev.first_vacuity_needle(text) is None


@pytest.mark.parametrize("line", ["planted vacuous output: Ran 0 tests",
                                  "as the probe input: Ran 0 tests", "verify_output=Ran 0 tests",
                                  "complete Ran 0 tests -> 400", "complete Ran 0 tests → 400"])
def test_marked_or_arrowed_needle_is_exempt(line):
    assert ev.first_vacuity_needle(line) is None, line


def test_the_needle_as_the_whole_output_still_refuses_quoted_or_not():
    assert ev.vacuity_problem("'Ran 0 tests'") is not None
    assert ev.vacuity_problem("Ran 0 tests in 0.000s") is not None


@pytest.mark.parametrize("text", ["Ran 0 tests overall, but 12 siblings held",
                                  "Ran 0 tests overall, but 8 distinct sha256s captured",
                                  "Ran 0 tests overall, but 17 probe jobs cancelled",
                                  "Ran 0 tests overall, logged x14 retries"])
def test_widened_counter_evidence_rescues(text, monkeypatch):
    assert ev.first_vacuity_needle(text) and ev.vacuity_problem(text) is None
    # mutation: without counter-evidence each one flips to refused -> the clause is load-bearing
    monkeypatch.setattr(ev, "measured_something", lambda t: None)
    assert ev.vacuity_problem(text) is not None


def test_counter_evidence_does_not_rescue_a_bare_needle():
    assert ev.vacuity_problem("Ran 0 tests overall, nothing else measured") is not None
    assert ev.measured_something("0 passed, 3 skipped in 0.11s") is None


def _payload(output="42 tests passed", **extra):
    return {"verify_cmd": "pytest -q", "verify_exit": 0, "verify_output": output, **extra}


def test_negative_control_is_opt_in():
    for p in (_payload(), _payload(control_cmd=""), _payload(control_cmd="  ")):
        assert ev.cannot_fail_problem(p) is None


def test_negative_control_outcomes():
    assert "supposed to FAIL" in ev.cannot_fail_problem(_payload(control_cmd="t", control_exit=0))
    assert ev.cannot_fail_problem(_payload(control_cmd="t", control_exit=1)) is None
    for code in (126, 127):
        assert "never ran" in ev.cannot_fail_problem(_payload(control_cmd="t", control_exit=code))
    for bad in ({}, {"control_exit": None}, {"control_exit": "0"}, {"control_exit": True}):
        assert "control_exit" in ev.cannot_fail_problem(_payload(control_cmd="t", **bad))


def test_vacuity_is_reported_before_the_control():
    p = _payload(output="Ran 0 tests in 0.000s", control_cmd="t", control_exit=1)
    assert "Ran 0 tests" in ev.cannot_fail_problem(p)


def test_self_attested_classification(tmp_path):
    f = tmp_path / "ev.md"
    f.write_text("x")
    own = [f"PROBE: sha256sum {f} => ^[0-9a-f]{{64}}", f"PROBE: stat -c %s {f} => ^1$"]
    assert ev.self_attested(own, str(f), bound=False) is True
    assert ev.self_attested(own, str(f), bound=True) is False             # COMMIT= binds work
    assert ev.self_attested(own + ["PROBE: test -e projects/demo/greet.py => ^ok$"], str(f), False) is False
    assert ev.self_attested(["PROBE: systemctl is-active app => ^active$"], str(f), False) is False
    assert ev.self_attested([], str(f), False) is False


# ---- through the API -----------------------------------------------------------------------

def _claimed(board):
    return board.insert_job("claimed", requested_by="orchestrator", assignee="orchestrator")


@pytest.mark.parametrize("payload,needle", [
    ({k: v for k, v in GOOD_EVIDENCE.items() if k != "verify_exit"}, "VERIFY_EXIT=0"),
    ({**GOOD_EVIDENCE, "verify_exit": 1}, "verify_exit is 1"),
    ({**GOOD_EVIDENCE, "verify_exit": True}, "VERIFY_EXIT=0"),
    ({**GOOD_EVIDENCE, "verify_cmd": " "}, "verify_cmd is missing"),
    ({**GOOD_EVIDENCE, "verify_output": ""}, "verify_output is empty"),
    ({**GOOD_EVIDENCE, "verify_output": "Ran 0 tests in 0.000s"}, "vacuous"),
    ({**GOOD_EVIDENCE, "control_cmd": "pytest tests/known_bad", "control_exit": 0},
     "supposed to FAIL"),
])
def test_close_refusals(board, payload, needle):
    job = _claimed(board)
    res = board.call("orchestrator", "POST", f"/api/jobs/{job}/close", payload)
    assert res.status_code == 422 and needle in res.json()["detail"], res.text
    assert board.status(job) == "claimed"


def test_close_refusal_lists_every_failing_field(board):
    res = board.call("orchestrator", "POST", f"/api/jobs/{_claimed(board)}/close", {})
    detail = res.json()["detail"]
    assert all(s in detail for s in ("verify_cmd", "VERIFY_EXIT=0", "verify_output"))


def test_close_accepts_good_evidence_and_records_it(board):
    job = _claimed(board)
    res = board.call("orchestrator", "POST", f"/api/jobs/{job}/close",
                     {**GOOD_EVIDENCE, "verify_output": "x" * 9000, "commit": "abc123",
                      "probes": ["PROBE: test -e app.py => ^ok$"]})
    assert res.status_code == 200, res.text
    stored = res.json()["evidence"]
    assert len(stored["verify_output"]) == ev.OUTPUT_CAP and stored["commit"] == "abc123"
    assert stored["probes"] == ["PROBE: test -e app.py => ^ok$"] and stored["self_attested"] is False
    assert res.json()["closed_by"] == "orchestrator"


def test_close_warns_on_missing_docs_and_self_attested(board, tmp_path):
    f = tmp_path / "ev.md"
    f.write_text("x")
    payload = {k: v for k, v in GOOD_EVIDENCE.items() if k != "docs"}
    payload.update(probes=[f"PROBE: sha256sum {f} => ^[0-9a-f]{{64}}"], evidence_path=str(f))
    res = board.call("orchestrator", "POST", f"/api/jobs/{_claimed(board)}/close", payload)
    assert res.status_code == 200
    warnings = " ".join(res.json()["warnings"])
    assert "DOCS:" in warnings and "SELF-ATTESTED" in warnings
    assert res.json()["evidence"]["self_attested"] is True
    listed = board.call("viewer", "GET", "/api/jobs?self_attested=true").json()["jobs"]
    assert [j["id"] for j in listed] == [res.json()["id"]]


@pytest.mark.parametrize("mode,code", [("strict", 422), ("warn", 200), ("off", 200)])
def test_vacuity_mode_switch(make_board, mode, code):
    b = make_board({"vacuity": mode})
    res = b.call("orchestrator", "POST", f"/api/jobs/{_claimed(b)}/close",
                 {**GOOD_EVIDENCE, "verify_output": "collected 0 items"})
    assert res.status_code == code, res.text
    if mode == "warn":
        assert any("vacuous" in w for w in res.json()["warnings"])
    if mode == "off":
        assert not any("vacuous" in w for w in res.json()["warnings"])


def test_evidence_mode_warn_still_records_a_close(make_board):
    b = make_board({"evidence": "warn"})
    res = b.call("orchestrator", "POST", f"/api/jobs/{_claimed(b)}/close", {"verify_cmd": "x"})
    assert res.status_code == 200 and any("VERIFY_EXIT" in w for w in res.json()["warnings"])
