"""`python -m konstant.release build` (DESIGN §11): the tarball excludes the
maintainer-only paths, a finding deletes it, preconditions refuse."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from konstant import __version__
from konstant.release import build as b

REPO = Path(__file__).resolve().parents[2]
DENY = REPO / "release" / "denylist.local.txt"
IP = ".".join(["10", "9", "8", "7"])


def git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@example.com", "-c", "user.name=t",
                    *args], check=True, capture_output=True)


@pytest.fixture()
def mini(tmp_path):
    """A tiny source tree with the release preconditions, committed."""
    root = tmp_path / "src"
    (root / "release").mkdir(parents=True)
    (root / "docs" / "build").mkdir(parents=True)
    shutil.copy(REPO / "release" / "patterns.toml", root / "release" / "patterns.toml")
    shutil.copy(REPO / ".gitattributes", root / ".gitattributes")
    (root / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{__version__}] - today\n")
    (root / "README.md").write_text("hello\n")
    shutil.copy(REPO / "get.sh", root / "get.sh")
    (root / "docs" / "PLAN.md").write_text(f"internal {IP}\n")
    (root / "docs" / "build" / "notes.md").write_text(f"internal {IP}\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def test_build_green_excludes_build_docs_and_writes_a_checkable_sum(mini, tmp_path):
    ok, text = b.build(mini, __version__, None, dist=tmp_path / "dist")
    assert ok, text
    tar = tmp_path / "dist" / f"konstant-{__version__}.tar.gz"
    names = b.tarball_names(tar)
    assert f"konstant-{__version__}/README.md" in names
    assert not [n for n in names if "PLAN.md" in n or "docs/build" in n or "denylist" in n]
    assert text.rstrip().endswith("RESULT: CLEAN") and "DENYLIST: SKIPPED" in text
    digest, name = (tmp_path / "dist" / f"{tar.name}.sha256").read_text().split()
    assert name == tar.name and digest == hashlib.sha256(tar.read_bytes()).hexdigest()
    res = subprocess.run(["sha256sum", "-c", f"{tar.name}.sha256"], cwd=tmp_path / "dist",
                         capture_output=True, text=True)
    assert res.returncode == 0 and ": OK" in res.stdout


def test_build_red_deletes_the_tarball(mini, tmp_path):
    (mini / "leak.md").write_text(f"host {IP}\n")
    git(mini, "add", "-A")
    git(mini, "commit", "-q", "-m", "leak")
    ok, text = b.build(mini, __version__, None, dist=tmp_path / "dist")
    assert not ok
    assert f"FINDING: konstant-{__version__}/leak.md:1:ipv4" in text
    assert not (tmp_path / "dist" / f"konstant-{__version__}.tar.gz").exists()
    assert not (tmp_path / "dist" / f"konstant-{__version__}.tar.gz.sha256").exists()
    assert (tmp_path / "dist" / "SCAN-REPORT.txt").read_text().rstrip().endswith("FINDINGS (1)")


def test_build_refuses_a_dirty_tree_unless_worktree(mini, tmp_path):
    (mini / "new.md").write_text("uncommitted\n")
    with pytest.raises(b.BuildError, match="not clean"):
        b.build(mini, __version__, None, dist=tmp_path / "dist")
    ok, _ = b.build(mini, __version__, None, dist=tmp_path / "dist", worktree=True)
    assert ok
    assert f"konstant-{__version__}/new.md" in b.tarball_names(
        tmp_path / "dist" / f"konstant-{__version__}.tar.gz")


def test_build_refuses_a_version_mismatch_and_a_missing_changelog_section(mini, tmp_path):
    with pytest.raises(b.BuildError, match="__init__"):
        b.build(mini, "9.9.9", None, dist=tmp_path / "dist")
    (mini / "CHANGELOG.md").write_text("# Changelog\n")
    with pytest.raises(b.BuildError, match="CHANGELOG"):
        b.check_version(mini, __version__)


def test_cli_build_requires_a_denylist_or_the_explicit_skip(tmp_path):
    res = subprocess.run([sys.executable, "-m", "konstant.release", "build", "--version",
                          __version__, "--dist", str(tmp_path)], capture_output=True, text=True,
                         cwd=REPO)
    assert res.returncode == 2 and "--no-denylist" in res.stderr


@pytest.mark.skipif(not DENY.is_file(), reason="maintainer-local denylist not present")
def test_the_real_tree_builds_clean_with_the_local_denylist(tmp_path):
    ok, text = b.build(REPO, __version__, DENY, dist=tmp_path, worktree=True)
    assert ok, text


def test_build_ships_get_sh_and_version_as_scanned_assets(mini, tmp_path):
    """dist/get.sh is the tarball's own get.sh, with a checkable .sha256, and dist/VERSION
    names the version get.sh resolves as latest; the report lists them."""
    dist = tmp_path / "dist"
    ok, text = b.build(mini, __version__, None, dist=dist)
    assert ok, text
    assert (dist / "get.sh").read_bytes() == (REPO / "get.sh").read_bytes()
    assert (dist / "get.sh").stat().st_mode & 0o111
    assert (dist / "VERSION").read_text() == __version__ + "\n"
    sha = hashlib.sha256((dist / "get.sh").read_bytes()).hexdigest()
    assert (dist / "get.sh.sha256").read_text() == f"{sha}  get.sh\n"
    assert "ASSETS: get.sh, VERSION" in text and f"GET_SH_SHA256: {sha}" in text
    assert subprocess.run(["sha256sum", "-c", "get.sh.sha256"], cwd=dist,
                          capture_output=True).returncode == 0


def test_a_finding_in_get_sh_fails_the_build_and_removes_the_assets(mini, tmp_path):
    (mini / "get.sh").write_text((mini / "get.sh").read_text() + f"# mirror {IP}\n")
    git(mini, "commit", "-qam", "plant")
    dist = tmp_path / "dist"
    ok, text = b.build(mini, __version__, None, dist=dist)
    assert not ok
    assert "dist/get.sh:" in text and "ipv4" in text
    assert not [p.name for p in dist.iterdir() if p.name != "SCAN-REPORT.txt"]


def test_a_release_without_get_sh_is_refused(mini, tmp_path):
    git(mini, "rm", "-q", "get.sh")
    git(mini, "commit", "-qm", "drop")
    with pytest.raises(b.BuildError, match="no get.sh"):
        b.build(mini, __version__, None, dist=tmp_path / "dist")
    assert not list((tmp_path / "dist").glob("*.tar.gz"))
