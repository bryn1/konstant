"""The public-safety scan (DESIGN §11): planted identifiers go red with file:line:pattern,
the clean shapes stay green. Planted values are assembled at run time so this file itself
carries none of them."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from konstant.release import scan

REPO = Path(__file__).resolve().parents[2]
PATTERNS = REPO / "release" / "patterns.toml"
IP = ".".join(["10", "1", "2", "3"])
MAIL = "someone" + "@" + "realmail.com"
GHP = "ghp" + "_" + "A1b2C3d4E5" * 3 + "F6g7H8"           # ghp_ + 36 chars
WORD = "zorb" + "lax"


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "konstant.release", *map(str, args)],
                          capture_output=True, text=True, cwd=cwd or REPO)


@pytest.fixture()
def planted(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.md").write_text(f"intro\nssh to {IP}\nmail {MAIL}\n")
    (tree / "b.py").write_text(f"x = 1\n# leaked {GHP} in a log\n# talk to {WORD.upper()} later\n")
    deny = tmp_path / "deny.txt"
    deny.write_text(f"# local names\n\n{WORD}\n")
    return tree, deny


def test_scan_red_names_each_planted_value(planted):
    tree, deny = planted
    res = _run("scan", "--tree", tree, "--denylist", deny)
    assert res.returncode == 1, res.stdout + res.stderr
    lines = [ln for ln in res.stdout.splitlines() if ln.startswith("FINDING: ")]
    assert lines == ["FINDING: a.md:2:ipv4", "FINDING: a.md:3:email",
                     "FINDING: b.py:2:github_token", "FINDING: b.py:3:denylist:3"]
    assert res.stdout.rstrip().endswith("RESULT: FINDINGS (4)")
    assert WORD not in res.stdout.lower()           # the report names the line, not the term


def test_scan_green_on_safe_shapes(tmp_path):
    (tmp_path / "ok.md").write_text("bind 127.0.0.1 or 0.0.0.0; docs use 192.0.2.7\n"
                                    "mail a@example.com, noreply@vendor.io\nversion 2.1.3\n"
                                    + "to" + "ken = os.environ['X']\n/home/<name>/x\n")
    res = _run("scan", "--tree", tmp_path, "--patterns", PATTERNS)
    assert res.returncode == 0, res.stdout
    assert "DENYLIST: SKIPPED" in res.stdout and res.stdout.rstrip().endswith("RESULT: CLEAN")


@pytest.mark.parametrize("text,pattern", [
    ("key -----BEGIN RSA PRIVATE " + "KEY-----\n", "private_key"),
    ("see /home/" + "jdoe/notes\n", "home_path"),
    ("deployed under /srv/" + "app1\n", "server_path"),
    ("fixed in TKT #" + "4821\n", "ticket_ref"),
    ("aws AKIA" + "ABCDEFGHIJKLMNOP\n", "cloud_key"),
    ("pass" + "word" + ' = "' + "Zx9" * 10 + '"\n', "assigned_secret"),
])
def test_each_pattern_goes_red(tmp_path, text, pattern):
    (tmp_path / "f.txt").write_text(text)
    res = scan.scan_files(tmp_path, ["f.txt"], scan.load_patterns(PATTERNS), None)
    assert [f.pattern for f in res.findings] == [pattern]


def test_a_file_name_is_scanned_too(tmp_path):
    (tmp_path / f"{WORD}-notes.md").write_text("nothing here\n")
    res = scan.scan_files(tmp_path, [f"{WORD}-notes.md"], scan.load_patterns(PATTERNS),
                          scan.load_denylist_lines([WORD]))
    assert [str(f) for f in res.findings] == [f"{WORD}-notes.md:0:denylist:1"]


def test_binary_files_are_counted_not_decoded(tmp_path):
    (tmp_path / "x.bin").write_bytes(b"\0\x01" + IP.encode())
    res = scan.scan_files(tmp_path, ["x.bin"], scan.load_patterns(PATTERNS), None)
    assert res.clean and res.binary == 1


def test_an_invalid_denylist_regex_is_matched_literally(tmp_path):
    rx = scan.load_denylist_lines(["a(b"])
    assert rx[0].regex.search("x A(B y")


def test_missing_patterns_file_is_a_usage_error(tmp_path):
    res = _run("scan", "--tree", tmp_path, "--patterns", tmp_path / "nope.toml")
    assert res.returncode == 2 and "nope.toml" in res.stderr


def test_git_tree_honours_export_ignore(tmp_path):
    g = tmp_path / "g"
    g.mkdir()
    (g / ".gitattributes").write_text("internal/ export-ignore\nnotes.md export-ignore\n")
    (g / "internal").mkdir()
    (g / "internal" / "x.md").write_text(f"{IP}\n")
    (g / "notes.md").write_text(f"{IP}\n")
    (g / "pub.md").write_text("fine\n")
    subprocess.run(["git", "init", "-q", str(g)], check=True)
    assert scan.tree_files(g) == [".gitattributes", "pub.md"]


def test_the_shipped_tree_is_clean():
    """The release tree itself carries no generic identifier (denylist: maintainer-local)."""
    res = scan.scan_files(REPO, scan.tree_files(REPO), scan.load_patterns(PATTERNS), None)
    assert res.clean, "\n".join(map(str, res.findings))
