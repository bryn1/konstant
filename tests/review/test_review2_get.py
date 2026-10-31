"""Second security review, G-06 and G-07: get.sh fails closed on a folder it cannot read and on tar link
members. Each test was written from the review's reproduction and red on the
reviewed code. The release is served by the local server of tests/release/test_get.py
in the GitHub layout (never the real URL)."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import tarfile

import pytest

from tests.release.test_get import TB, V, Server, oneliner
from tests.release.test_get import cwd, dist  # noqa: F401  (fixtures)


def serve(dist_dir, tmp_path, tarball: bytes | None = None) -> Server:
    """dist/ in the GitHub layout; `tarball` replaces the release (its .sha256 recomputed, so
    only the member check stands between it and the folder)."""
    root = tmp_path / "srv"
    latest, tagged = root / "latest" / "download", root / "download" / f"v{V}"
    latest.mkdir(parents=True)
    tagged.mkdir(parents=True)
    for f in ("get.sh", "VERSION"):
        shutil.copy(dist_dir / f, latest / f)
    shutil.copy(dist_dir / "get.sh", tagged / "get.sh")
    data = tarball if tarball is not None else (dist_dir / TB).read_bytes()
    (tagged / TB).write_bytes(data)
    (tagged / f"{TB}.sha256").write_text(f"{hashlib.sha256(data).hexdigest()}  {TB}\n")
    return Server(root)


@pytest.fixture()
def server(dist, tmp_path):  # noqa: F811
    made = []

    def make(tarball=None):
        made.append(serve(dist, tmp_path, tarball))
        return made[-1]
    yield make
    for s in made:
        s.httpd.shutdown()
        s.httpd.server_close()


def with_member(dist_dir, kind: str) -> bytes:
    """The real release plus one link member under konstant-<V>/."""
    src = tarfile.open(dist_dir / TB, "r:gz")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as out:
        for m in src.getmembers():
            out.addfile(m, src.extractfile(m) if m.isfile() else None)
        link = tarfile.TarInfo(f"konstant-{V}/evil")
        if kind == "symlink-absolute":
            link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        elif kind == "symlink-escape":
            link.type, link.linkname = tarfile.SYMTYPE, "../../../outside"
        else:
            link.type, link.linkname = tarfile.LNKTYPE, f"konstant-{V}/install.sh"
        out.addfile(link)
    return buf.getvalue()


def test_G06_an_unreadable_non_empty_dir_is_refused(server, cwd):  # noqa: F811
    srv = server()
    d = cwd / "d5"
    d.mkdir()
    (d / "precious").write_text("mine\n")
    d.chmod(0o300)
    try:
        res = oneliner(srv, cwd, "--no-install", "--yes", "--dir", "d5", shell="dash"
                       if shutil.which("dash") else "bash")
    finally:
        d.chmod(0o700)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "cannot be read" in res.stderr
    assert sorted(p.name for p in d.iterdir()) == ["precious"]       # nothing unpacked beside it
    assert srv.downloads() == []


def test_G06_an_empty_writable_dir_still_installs(server, cwd):  # noqa: F811
    """The twin: the fail-closed check refuses nothing it should accept."""
    srv = server()
    (cwd / "empty").mkdir()
    res = oneliner(srv, cwd, "--no-install", "--yes", "--dir", "empty")
    assert res.returncode == 0, res.stderr
    assert (cwd / "empty" / "install.sh").is_file()


@pytest.mark.parametrize("kind", ["symlink-absolute", "symlink-escape", "hardlink"])
def test_G07_a_link_member_is_refused_before_unpacking(server, dist, cwd, kind):  # noqa: F811
    srv = server(with_member(dist, kind))
    res = oneliner(srv, cwd, "--no-install", "--yes")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "unsafe member" in res.stderr and "evil" in res.stderr
    assert not (cwd / "konstant").exists(), list((cwd / "konstant").iterdir())
    assert not os.path.lexists(cwd / "outside")


def test_G07_the_real_release_has_only_files_and_folders(dist):  # noqa: F811
    """The rule refuses every link because the release ships none (checked here)."""
    with tarfile.open(dist / TB, "r:gz") as t:
        odd = [m.name for m in t.getmembers() if not (m.isfile() or m.isdir())]
    assert not odd, odd
