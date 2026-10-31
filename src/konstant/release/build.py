"""`python -m konstant.release build --version V [--denylist PATH | --no-denylist]` (DESIGN §11).

1. Preconditions: `konstant.__version__` == V and CHANGELOG.md has a `## [V]` (or `## V`) section;
   the work tree is clean (or `--worktree`: archive the current tracked + untracked-not-ignored
   files through a temporary index, for the fresh-install test before a commit).
2. `git archive --prefix=konstant-V/` | gzip -n -> dist/konstant-V.tar.gz; `export-ignore` in
   .gitattributes keeps maintainer-only paths (private planning notes, the local denylist) out.
3. Scan every member (release/scan.py) + refuse any maintainer-only path that slipped in. Any
   finding: the tarball is deleted, dist/SCAN-REPORT.txt lists file:line:pattern, exit 1.
4. Clean: dist/konstant-V.tar.gz.sha256 (`sha256sum` format, bare file name, so
   `sha256sum -c` works next to the downloaded tarball) and SCAN-REPORT.txt ending RESULT: CLEAN.
5. The one-line install assets (DESIGN §10.1): dist/get.sh, taken from the tarball's own
   get.sh (so it is the scanned text of this release), its .sha256, and dist/VERSION (the version
   get.sh resolves as "latest"). Both are scanned as files of their own; a finding there fails
   the build like one in the tarball.
"""
from __future__ import annotations

import gzip
import hashlib
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

from konstant import __version__
from konstant.release import scan

# maintainer-only paths (private planning notes, the local denylist): never in a release,
# whatever .gitattributes says (belt and braces for export-ignore)
FORBIDDEN = re.compile(r"^docs/(INVENTORY|PLAN|OPEN-QUESTIONS)\.md$|^docs/build/|^release/denylist")


class BuildError(Exception):
    pass


def _git(root: Path, *args, env=None, input_=None) -> bytes:
    res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, env=env,
                         input=input_)
    if res.returncode != 0:
        raise BuildError(f"git {' '.join(args)}: {res.stderr.decode(errors='replace').strip()}")
    return res.stdout


def check_version(root: Path, version: str) -> None:
    if version != __version__:
        raise BuildError(f"--version {version} but src/konstant/__init__.py says {__version__}")
    log = root / "CHANGELOG.md"
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    if not re.search(rf"^## \[?{re.escape(version)}\]?(\s|$)", text, re.M):
        raise BuildError(f"CHANGELOG.md has no '## [{version}]' section")


def tree_ish(root: Path, worktree: bool) -> str:
    if not worktree:
        dirty = _git(root, "status", "--porcelain").decode().strip()
        if dirty:
            raise BuildError("the work tree is not clean (commit first, or pass --worktree to "
                             "archive the current files):\n" + dirty)
        return "HEAD"
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        _git(root, "read-tree", "HEAD", env=env)
        _git(root, "add", "-A", env=env)
        return _git(root, "write-tree", env=env).decode().strip()


def archive(root: Path, version: str, ref: str, dest: Path) -> None:
    raw = _git(root, "archive", "--format=tar", f"--prefix=konstant-{version}/", ref)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh, gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0) as gz:
        gz.write(raw)


def scan_tarball(path: Path, patterns: list, denylist: list | None) -> scan.Result:
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(path, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        for m in members:
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                raise BuildError(f"unsafe member path in the archive: {m.name}")
            if hasattr(tarfile, "data_filter"):
                tar.extract(m, tmp, filter="data")
            else:  # pragma: no cover - Python without PEP 706
                tar.extract(m, tmp)
        rels = [m.name for m in members]
        res = scan.scan_files(Path(tmp), rels, patterns, denylist)
        prefix = re.compile(r"^[^/]+/")
        res.findings += [scan.Finding(r, 0, "build-document")
                         for r in rels if FORBIDDEN.search(prefix.sub("", r))]
        return res


ASSETS = ("get.sh", "VERSION")


def write_assets(tarball: Path, version: str, dist: Path) -> None:
    """dist/get.sh (from the tarball, mode 0755) and dist/VERSION."""
    with tarfile.open(tarball, "r:gz") as tar:
        try:
            member = tar.extractfile(f"konstant-{version}/get.sh")
        except KeyError:
            member = None
        if member is None:
            raise BuildError("the tarball has no get.sh (the one-line installer must ship)")
        data = member.read()
    (dist / "get.sh").write_bytes(data)
    (dist / "get.sh").chmod(0o755)
    (dist / "VERSION").write_text(version + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(root: Path, version: str, denylist: Path | None, dist: Path | None = None,
          worktree: bool = False, patterns_path: Path | None = None) -> tuple:
    """Returns (ok, report text). Writes dist/: tarball + .sha256 + SCAN-REPORT.txt."""
    root = Path(root).resolve()
    dist = Path(dist) if dist else root / "dist"
    check_version(root, version)
    pats = scan.load_patterns(patterns_path or root / "release" / "patterns.toml")
    deny = scan.load_denylist(denylist) if denylist else None
    ref = tree_ish(root, worktree)
    tarball = dist / f"konstant-{version}.tar.gz"
    sumfile = dist / f"{tarball.name}.sha256"
    report_path = dist / "SCAN-REPORT.txt"
    outputs = [sumfile, dist / "get.sh", dist / "get.sh.sha256", *(dist / a for a in ASSETS)]
    for f in outputs:
        f.unlink(missing_ok=True)
    archive(root, version, ref, tarball)
    res = scan_tarball(tarball, pats, deny)
    try:
        write_assets(tarball, version, dist)
    except BuildError:
        tarball.unlink(missing_ok=True)
        raise
    assets = scan.scan_files(dist, list(ASSETS), pats, deny)
    res.files += assets.files
    res.binary += assets.binary
    res.findings += [scan.Finding(f"dist/{f.path}", f.line, f.pattern) for f in assets.findings]
    digest = sha256(tarball)
    head = [f"VERSION: {version}", f"TARBALL: {tarball.name}", f"SOURCE: {ref}",
            f"SHA256: {digest}" if res.clean else "SHA256: (tarball deleted)",
            "ASSETS: " + ", ".join(ASSETS) + " (scanned with the tarball)"]
    if res.clean:
        head.append(f"GET_SH_SHA256: {sha256(dist / 'get.sh')}")
    text = scan.report(res, head)
    report_path.write_text(text, encoding="utf-8")
    if not res.clean:
        for f in (tarball, *outputs):
            f.unlink(missing_ok=True)
        return False, text
    sumfile.write_text(f"{digest}  {tarball.name}\n", encoding="utf-8")
    (dist / "get.sh.sha256").write_text(f"{sha256(dist / 'get.sh')}  get.sh\n", encoding="utf-8")
    return True, text


def tarball_names(path: Path) -> list:
    with tarfile.open(path, "r:gz") as tar:
        return tar.getnames()


__all__ = ["BuildError", "build", "tarball_names"]
