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
