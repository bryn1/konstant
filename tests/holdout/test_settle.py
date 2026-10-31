"""settle() with holdouts (docs/LEVEL5.md 3.6 step 4): holdouts add a condition and never replace
one. Pure: the holdout result dicts are what verify/holdout.evaluate returns."""
from __future__ import annotations

import pytest

from konstant.verify.verifier import settle

M = {"error": None, "matched": True, "line": "PROBE: m", "output": "ok", "source": "dod"}
C = {"error": None, "matched": False, "line": "PROBE: c", "output": "absent"}
RR_OK = {"ran": True, "ok": True, "exit": 0, "timed_out": False}


def H(**kw) -> dict:
    base = {"rows": [{"hid": "H1", "passed": True}, {"hid": "H2", "passed": True}],
            "failed": [], "leak": [], "suspect": [], "integrity": [], "blocked": [],
            "commit": "c" * 40, "min_per_job": 2}
    base.update(kw)
    return base


FAILED = H(rows=[{"hid": "H1", "passed": False}, {"hid": "H2", "passed": True}],
           failed=[("H1", "names other than the default are used verbatim")])


def test_settle_green_every_holdout_passed():
    verdict, reasons = settle([M], RR_OK, H())
    assert verdict == "PASS" and reasons[-1] == "2 holdout(s) passed on commit cccccccccccc"


def test_settle_green_without_holdouts_is_level4():
    assert settle([M], RR_OK, None) == settle([M], RR_OK)


@pytest.mark.parametrize("probes,rerun,h,want,needle", [
    ([M], RR_OK, FAILED, "FAIL",
     "holdout H1 failed (hint: names other than the default are used verbatim)"),
    ([M], RR_OK, H(suspect=["LEAK-SUSPECT: a literal of H2 appears on an added line of g.py"]),
     "FAIL", "LEAK-SUSPECT"),
    ([M], RR_OK, H(integrity=["LEAK: canary of H1 found in greeter.py"],
                   leak=["LEAK: canary of H1 found in greeter.py"]),
     "BLOCKED", "LEAK: canary of H1 found in greeter.py"),
    ([C], RR_OK, H(integrity=["holdout commitment mismatch: H1"]), "BLOCKED",
     "holdout commitment mismatch: H1"),           # integrity outranks even a level-4 FAIL
    ([M], RR_OK, H(blocked=["holdout H2 could not run (timeout)"]), "BLOCKED",
     "could not run"),
    ([M], RR_OK, H(rows=[{"hid": "H1", "passed": True}]), "BLOCKED", "holdouts incomplete"),
    ([C], RR_OK, H(), "FAIL", "contradiction"),     # a level-4 FAIL stays a FAIL
    ([], RR_OK, H(), "BLOCKED", "nothing independent verified"),   # holdouts alone never pass
    ([C], RR_OK, FAILED, "FAIL", "holdout H1 failed"),
])
def test_settle_red(probes, rerun, h, want, needle):
    verdict, reasons = settle(probes, rerun, h)
    assert verdict == want and any(needle in r for r in reasons), (verdict, reasons)


def test_settle_red_reasons_carry_no_scenario_content():
    _v, reasons = settle([M], RR_OK, FAILED)
    text = " ".join(reasons)
    assert "Ada" not in text and "RUN" not in text and "khc-" not in text
