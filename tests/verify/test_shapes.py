"""Every allowlisted shape has an accepted and a refused case; metacharacters are refused
BEFORE shape matching; operands outside path_roots (also via symlink) are refused."""
from __future__ import annotations

import os

import pytest

from konstant.verify import probe, shapes
from konstant.verify.shapes import META_REASON, Roots, parse_command

SHA = "abc1234"


def accepted(cmd, roots):
    return parse_command(cmd, roots)


def refusal(cmd, roots) -> str:
    with pytest.raises(ValueError) as exc:
        parse_command(cmd, roots)
    return str(exc.value)


GREEN = [
    ("test -e f.txt", "test"), ("test -f f.txt", "test"), ("test -d d", "test"),
    ("ls -ld f.txt", "ls"), ("stat -c %s f.txt", "stat"), ("sha256sum f.txt", "sha256"),
    ("grep -c one f.txt", "grep"),
    ("git -C repo rev-parse HEAD", "git"), ("git -C repo rev-parse --verify main", "git"),
    ("git -C repo log -1 --format=%H HEAD", "git"), ("git -C repo log -1 --format=%ae HEAD", "git"),
    ("git -C repo log -1 --format=%s HEAD", "git"),
    (f"git -C repo branch -r --contains {SHA}", "git"), ("git -C repo blob-sha256 HEAD:f.txt", "blob"),
    ("curl -s http://127.0.0.1:9/x", "curl"),
    ("curl -s -o /dev/null -w %{http_code} http://localhost:9/x", "curl"),
    ("systemctl is-active demo", "systemctl"), ("systemctl --user is-enabled demo", "systemctl"),
    ("systemctl show demo -p ActiveState", "systemctl"),
    ("systemctl --user show demo -p MainPID", "systemctl"),
    ("docker inspect -f {{.State.Status}} web", "docker"),
    ('sqlite3 -readonly data.db "SELECT a, b FROM t"', "sqlite"),
    ("git --version", "version"), ("konstant job show 12.3 --json", "konstant"),
]


@pytest.mark.parametrize("cmd,name", GREEN)
def test_shape_accepted_green(cmd, name, roots):
    assert accepted(cmd, roots).name == name


RED = [
    "test -x f.txt", "test -e", "ls -l f.txt", "ls -ld f.txt d", "stat -c %s", "stat f.txt",
    "sha256sum f.txt d", "sha256sum", "grep -c -R one f.txt", "grep -c one", "grep one f.txt",
    "git -C repo push origin main", "git -C repo rev-parse HEAD~1", "git -C repo log -1 --format=%b HEAD",
    "git -C repo log -1 --format=%H -p", "git -C repo branch -r --contains main",
    "git -C repo status", "git -C repo ls-remote https://example.invalid/x main",
    # REVIEW F-04: shapes that run repo-configured commands (a clean filter, an uploadpack)
    "git -C repo status --porcelain", "git -C repo ls-remote origin main",
    "git -C repo blob-sha256 HEAD:/etc/passwd", "git -C repo blob-sha256 HEAD",
    "git log -1 --format=%H HEAD",
    "curl -s http://example.com/", "curl -sL http://127.0.0.1:9/", "curl -s -X POST http://127.0.0.1:9/",
    "curl -s ftp://127.0.0.1/x", "curl -s http://user@127.0.0.1:9/x",
    "curl -s -o out.txt -w %{http_code} http://127.0.0.1:9/",
    "systemctl restart demo", "systemctl is-active", "systemctl show demo",
    "docker inspect -f {{.Config.Env}} web", "docker inspect -f {{json .}} web",
    "docker inspect -f {{.State.Status}}", "docker run web",
    'sqlite3 -readonly data.db "DELETE FROM t"', 'sqlite3 data.db "SELECT 1"',
    'sqlite3 -readonly data.db ".tables"',
    "/usr/bin/git --version", "git --version extra", "no-such-binary-xyz --version",
    "konstant job list --json", "konstant job show abc --json", "konstant job show 1",
    "cat f.txt", "rm -rf d", "python3 -c 1",
]


@pytest.mark.parametrize("cmd", RED)
def test_shape_refused_red(cmd, roots):
    assert refusal(cmd, roots)


@pytest.mark.parametrize("cmd", [
    "test -e f.txt; rm -rf d", "ls -ld f.txt | cat", "ls -ld $(echo f.txt)", "ls -ld `echo f.txt`",
    "ls -ld f.txt > out", "ls -ld < f.txt", "test -e f.txt & echo", 'grep -c "a|b" f.txt',
    "cat f.txt; whatever", "rm -rf d && true", "echo $HOME", "test -e f.txt\nrm x",
    "test -e ../x", "git -C repo/../repo rev-parse HEAD", "test -e a\x00b",
])
def test_metacharacters_refused_before_shape_matching_red(cmd, roots):
    assert refusal(cmd, roots) == META_REASON      # not "not an allowlisted shape"


def test_metacharacter_check_runs_before_the_root_check(roots):
    assert refusal("test -e /etc/passwd;", roots) == META_REASON


def test_path_outside_roots_refused_red(roots):
    assert "outside the allowed roots" in refusal("test -e /etc/passwd", roots)
    assert "outside the allowed roots" in refusal("git -C /tmp rev-parse HEAD", roots)
    assert "outside the allowed roots" in refusal('sqlite3 -readonly /etc/x.db "SELECT 1"', roots)


def test_path_inside_roots_accepted_green(roots, home):
    assert accepted(f"test -e {home}/f.txt", roots).native == ("test", ("-e", f"{home}/f.txt"))
    assert accepted("test -e f.txt", roots).native[1][1] == str(home / "f.txt")


def test_symlink_pointing_outside_refused_red(roots, home, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    os.symlink(outside, home / "escape")
    assert "outside the allowed roots" in refusal("sha256sum escape", roots)
    os.symlink(tmp_path, home / "dirlink")
    assert "outside the allowed roots" in refusal("test -e dirlink/outside.txt", roots)


def test_symlink_pointing_inside_accepted_green(roots, home):
    os.symlink(home / "f.txt", home / "inside")
    assert accepted("sha256sum inside", roots).name == "sha256"


def test_extra_root_widens_the_allowed_set_green(home, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    r = Roots.build(home, {"path_roots": ["."], "url_hosts": ["127.0.0.1"]}, [str(other)])
    assert accepted(f"test -d {other}", r).name == "test"
    assert "url_hosts" in refusal("curl -s http://localhost:9/", r)


def test_roots_build_resolves_config_against_home_green(home):
    r = Roots.build(home, {"path_roots": ["d"]}, [])
    assert accepted("test -e d/x", r).name == "test"
    assert "outside" in refusal("test -e f.txt", r)


def test_docker_format_with_secret_words_refused_red(roots):
    for word in ("Env", "json", "Config", "secret", "Labels"):
        assert refusal("docker inspect -f {{.%s}} web" % word, roots)


@pytest.mark.parametrize("expect", [".*", ".", "^", r"\w", "[0-9]+", "", "ok|", "x*", "$"])
def test_trivial_regex_refused_red(expect, roots):
    reason = probe.check_line(f"PROBE: test -e f.txt => {expect}", roots)
    assert reason and "trivial" in reason


def test_specific_regex_accepted_green(roots):
    assert probe.check_line("PROBE: test -e f.txt => ^ok$", roots) is None


def test_blob_expectation_must_pin_the_hash_red(roots):
    assert "must begin" in probe.check_line("PROBE: git -C repo blob-sha256 HEAD:f.txt => f.txt", roots)
    assert probe.check_line(
        "PROBE: git -C repo blob-sha256 HEAD:f.txt => ^sha256: [0-9a-f]{64}", roots) is None


def test_the_hygiene_limit_holds_for_this_package():
    from pathlib import Path
    for f in Path(shapes.__file__).parent.glob("*.py"):
        assert len(f.read_text().splitlines()) <= 400, f
