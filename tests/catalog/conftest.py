"""Fixtures for the catalog + generator tests: a copy of the shipped catalog and a temp workspace."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from konstant import catalog

SRC = catalog._source_root()


@pytest.fixture()
def cat_copy(tmp_path) -> Path:
    """A writable copy of the shipped catalog (planted-bad cases edit it)."""
    root = tmp_path / "catalog"
    shutil.copytree(SRC, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


@pytest.fixture()
def workspace(tmp_path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws
