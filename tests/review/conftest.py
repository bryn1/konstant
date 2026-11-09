"""Fixtures for the security-review tests (docs/CONCEPTS.md "Security reviews"): each test is
named for the finding it pins (test_F<nn>_..., test_G<nn>_...). Every test was written from the
review's reproduction and was red on the reviewed code before the fix."""
from __future__ import annotations

import pytest

from tests.gate.conftest import Scenario


@pytest.fixture()
def scen(tmp_path):
    return lambda **kw: Scenario(tmp_path, **kw)


from tests.board.conftest import board, make_board  # noqa: E402,F401  (board API fixtures)
from tests.cli.conftest import fresh  # noqa: E402,F401  (an uninitialised CLI workspace)

# fixtures from other suites, reused by the L5-R1 finding tests (tests/review/test_level5_r1.py)
from tests.holdout.conftest import hws, hws_manual  # noqa: E402,F401
from tests.factory.conftest import fws  # noqa: E402,F401
from tests.factory.test_open_profile import pws  # noqa: E402,F401
from tests.memory.conftest import mb  # noqa: E402,F401
