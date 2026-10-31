"""Standing rule: no file under src/ over 400 lines without a `reason:` line in its first
5 lines; test files <= 600. The check itself is tested red on a planted oversize file."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_LIMIT, TEST_LIMIT = 400, 600


def violations(files, limit):
    out = []
    for f in files:
        lines = f.read_text(encoding="utf-8").splitlines()
        if len(lines) > limit and not any("reason:" in ln for ln in lines[:5]):
            out.append(f"{f}: {len(lines)} lines")
    return out


def test_src_files_within_limit():
    files = sorted((ROOT / "src").rglob("*.py"))
    assert files and violations(files, SRC_LIMIT) == []


def test_test_files_within_limit():
    assert violations(sorted((ROOT / "tests").rglob("*.py")), TEST_LIMIT) == []


def test_the_check_goes_red_on_a_planted_oversize_file(tmp_path):
    big = tmp_path / "big.py"
    big.write_text("x = 1\n" * (SRC_LIMIT + 1))
    assert violations([big], SRC_LIMIT)
    big.write_text("# reason: generated table\n" + "x = 1\n" * (SRC_LIMIT + 1))
    assert violations([big], SRC_LIMIT) == []
