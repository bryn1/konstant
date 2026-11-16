"""The memory guard and a literal that one job's brief makes public (wave L5-L, live run 2).

Live: two held-out literals of the README job's sealed set stood verbatim in the code job's own
DoD. The guard judged a note only against the brief of the job whose SCENARIO holds a literal,
so every note of the code job that quoted its own DoD was refused, written on its trail, and the
verifier failed the code job's round with a LEAK-SUSPECT while its own holdouts all passed. A
literal the writing phase's own brief shows is public to that phase; any other held-out literal
is still refused.
"""
from __future__ import annotations

import pytest

from konstant.holdout import lint
from konstant.memory import guard

SCENARIO = """SCENARIO: the README shows the CLI's worked example
KIND: proof
RUN: python3 greeter.py Quintessa
EXPECT_EXIT: 0
EXPECT_OUT: hello Quintessa
HINT: the README documents a worked example of the command line
CANARY: khc-0123456789abcdef0123
"""


def store(tmp_path):
    root = tmp_path / "holdout"
    (root / "3").mkdir(parents=True)
    (root / "3" / "H1.scenario").write_text(SCENARIO)
    lint.parse(SCENARIO.encode(), "H1")                     # a well-formed held-out scenario
    return root


BRIEFS = {2: "B1: greet a name. DoD: `python3 greeter.py Quintessa` prints hello Quintessa",
          3: "B2: the README documents greet(name) and the CLI"}


def test_a_literal_the_writers_own_brief_shows_is_public_red(tmp_path):
    note = "DoD-3: `python3 greeter.py Quintessa` prints hello Quintessa (from my brief)"
    guard.scan(note, store(tmp_path), BRIEFS.get, writer_job=2)       # accepted


def test_the_same_note_from_another_job_is_still_refused_green(tmp_path):
    note, root = "tip: `python3 greeter.py Quintessa` prints hello Quintessa", store(tmp_path)
    with pytest.raises(guard.StoreRefused) as exc:
        guard.scan(note, root, BRIEFS.get, writer_job=4)
    assert exc.value.kind == "literal"
    with pytest.raises(guard.StoreRefused):
        guard.scan(note, root, BRIEFS.get)                              # no writer job


def test_a_canary_is_refused_whatever_the_writers_brief_green(tmp_path):
    with pytest.raises(guard.StoreRefused) as exc:
        guard.scan("keep khc-0123456789abcdef0123", store(tmp_path), BRIEFS.get, writer_job=2)
    assert exc.value.kind == "canary"
