"""DoD extraction (a hard filing requirement) and the row lint (warnings), both directions."""
from __future__ import annotations

import pytest

from konstant.board import dod


@pytest.mark.parametrize("brief", [
    "Do X.\nDoD: tests pass",
    "Do X.\n## Acceptance criteria: the file exists",
    "- DoD: greet() returns hello",
    "Definition of Done - report written",
    "Do X.\nAcceptance:\n- one\n- two",
    "dod: lower case works",
])
def test_acceptance_is_found(brief):
    assert dod.extract_acceptance(brief)


@pytest.mark.parametrize("brief", ["Do X and make it good.", "", "DoD:", "DoD:   \n\n",
                                   "We need a dodgy fix", "Acceptance is important"])
def test_no_acceptance(brief):
    assert dod.extract_acceptance(brief) == ""


def test_acceptance_runs_to_the_end_of_the_brief():
    brief = "Context.\nDoD: a\n- b\n\nPROBE: test -e x => ^ok$\n"
    assert dod.extract_acceptance(brief) == "DoD: a\n- b\n\nPROBE: test -e x => ^ok$"


@pytest.mark.parametrize("row,cls", [
    ("DoD: never spawn subagents", "NEG"),
    ("DoD: the service is deployed and is active", "LIVE"),
    ("DoD: the page looks right", "VISUAL"),
    ("DoD: x\n- do not touch the config", "CONSTRAINT"),
])
def test_lint_flags(row, cls):
    assert cls in {c for c, _ in dod.lint(row)}


@pytest.mark.parametrize("row", [
    "DoD: pytest tests/test_greet.py exits 0",
    "DoD: the service is active; PROBE: systemctl is-active app => ^active$",
    "DoD: the service is active\nPROBE: systemctl is-active app => ^active$",
    "DoD: the page has overflow=0 and contrast ratio 4.5",
    "DoD: do not touch app/ files outside app/x.py",
])
def test_lint_leaves_checkable_rows_alone(row):
    rows = [r for r in dod.lint(row) if r[0] != "NOPROBE"]     # NOPROBE: its own tests below
    assert rows == [], rows


def test_lint_noprobe_red_without_a_line_start_probe():
    # REVIEW F-02: verify passes only on a matched DoD probe; the verifier collects PROBE lines
    # that START a line, so an inline `; PROBE:` is not one either
    assert ("NOPROBE", "pytest tests/test_greet.py exits 0") in \
        dod.lint("DoD: pytest tests/test_greet.py exits 0")
    assert any(c == "NOPROBE" for c, _ in dod.lint(
        "DoD: the service is active; PROBE: systemctl is-active app => ^active$"))


def test_lint_noprobe_green_with_a_probe_line():
    assert not any(c == "NOPROBE" for c, _ in dod.lint(
        "DoD: the service is active\nPROBE: systemctl is-active app => ^active$"))


def test_add_returns_lint_warnings_but_files(board):
    res = board.add(brief="Do it.\nDoD: the app is deployed")
    assert res.status_code == 200 and any("LIVE" in w for w in res.json()["warnings"])
