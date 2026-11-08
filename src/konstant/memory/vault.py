"""The vault on disk: `memory/` in the workspace, its own git repository, one commit per write.

Only the board process writes here (every phase reaches memory through the board: the vault is in
machinery.DIRS, not writable, and machinery.SEALED, not readable). The owner's own tools (an
editor, Obsidian) may edit it; konstant never commits their edits, and recall serves them only
when `[confinement] memory_share` is on (guard.py).

Commits use plumbing under the pinned git environment of gate/rules/common.py (no system or
global config, hooks off, no fsmonitor, no transport: F-04) and a TEMPORARY index built from
HEAD, so a commit holds exactly konstant's one file even when the owner has staged other
changes; the repository's own index is then updated for that path only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from konstant.gate.rules.common import GIT_ISOLATION, git_env

BRANCH = "main"
SKIP_DIRS = (".git", ".obsidian", ".trash")
_SEG = re.compile(r"^(?!\.)[^/\\\x00-\x1f]{1,120}$")
NOTE_MAX = 256 * 1024          # a bigger file is not indexed (the owner's attachments, exports)


class VaultError(Exception):
    """The vault cannot be written: the write is refused, never half done."""


def safe_rel(rel: str) -> str:
    """A vault-relative note path: posix segments, no hidden segment, no `..`, ends in `.md`."""
    rel = str(rel).replace("\\", "/")
    parts = rel.split("/")
    if not rel.endswith(".md") or rel.startswith("/") or \
            any(not _SEG.match(p) or p in (".", "..") for p in parts):
        raise VaultError(f"not a vault note path: {rel!r}")
    return rel


class Vault:
    def __init__(self, root):
        self.root = Path(root)

    # --- reading ------------------------------------------------------------------------
    def files(self) -> list:
        """Every note (vault-relative path), sorted; hidden and tool folders skipped."""
        out = []
        if not self.root.is_dir():
            return out
        for d, dirs, names in os.walk(self.root):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
            for n in sorted(names):
                if n.endswith(".md") and not n.startswith("."):
                    p = Path(d) / n
                    if p.is_file() and not p.is_symlink():
                        out.append(p.relative_to(self.root).as_posix())
        return out

    def path(self, rel: str) -> Path:
        p = self.root / safe_rel(rel)
        real, root = os.path.realpath(p), os.path.realpath(self.root)
        if not real.startswith(root.rstrip("/") + "/"):
            raise VaultError(f"{rel!r} leaves the vault")
        return p

    def read(self, rel: str) -> str:
        p = self.path(rel)
        if p.is_symlink() or not p.is_file():
            raise FileNotFoundError(rel)
        with open(p, "rb") as fh:
            data = fh.read(NOTE_MAX + 1)
        if len(data) > NOTE_MAX:
            raise VaultError(f"{rel} is over {NOTE_MAX // 1024} KiB")
        return data.decode("utf-8", "replace")

    # --- git ----------------------------------------------------------------------------
    def _git(self, *args, env=None, data: bytes | None = None) -> subprocess.CompletedProcess:
        r = subprocess.run(["git", *GIT_ISOLATION, "-C", str(self.root), *args],
                           capture_output=True, input=data, timeout=60,
                           env={**git_env(), **(env or {})})
        return r

    def _must(self, r, what: str) -> str:
        if r.returncode != 0:
            raise VaultError(f"memory git {what} failed: "
                             f"{(r.stderr or r.stdout).decode('utf-8', 'replace').strip()[-300:]}")
        return r.stdout.decode("utf-8", "replace").strip()

    def ensure(self) -> None:
        """The vault dir (0700) and its own git repository (no template: no hooks)."""
        if shutil.which("git") is None:
            raise VaultError("memory needs git (every write is a commit in memory/.git)")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        if not (self.root / ".git").exists():
            self._must(self._git("init", "-q", "--template="), "init")
            self._must(self._git("symbolic-ref", "HEAD", f"refs/heads/{BRANCH}"), "symbolic-ref")

    def head(self) -> str | None:
        r = self._git("rev-parse", "--verify", "-q", "HEAD^{commit}")
        return r.stdout.decode().strip() if r.returncode == 0 and r.stdout.strip() else None

    def write(self, rel: str, text: str, actor: str, message: str) -> str:
        """Write one note atomically (0600) and commit exactly that file as `actor`. Returns the
        commit id."""
        self.ensure()
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if p.is_symlink():
            raise VaultError(f"{rel} is a symlink: konstant never writes through one")
        data = text.encode("utf-8")
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".konstant-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return self.commit(safe_rel(rel), data, actor, message)

    def commit(self, rel: str, data: bytes, actor: str, message: str) -> str:
        blob = self._must(self._git("hash-object", "-w", "--no-filters", "--stdin", data=data),
                          "hash-object")
        head = self.head()
        fd, index = tempfile.mkstemp(prefix="konstant-memidx-")
        os.close(fd)
        os.unlink(index)
        ienv = {"GIT_INDEX_FILE": index}
        try:
            self._must(self._git("read-tree", *([head] if head else ["--empty"]), env=ienv),
                       "read-tree")
            self._must(self._git("update-index", "--add", "--cacheinfo",
                                 f"100644,{blob},{rel}", env=ienv), "update-index")
            tree = self._must(self._git("write-tree", env=ienv), "write-tree")
        finally:
            Path(index).unlink(missing_ok=True)
        who = {"GIT_AUTHOR_NAME": f"konstant {actor}",
               "GIT_AUTHOR_EMAIL": f"{actor}@konstant.invalid",
               "GIT_COMMITTER_NAME": "konstant", "GIT_COMMITTER_EMAIL": "board@konstant.invalid"}
        parent = ["-p", head] if head else []
        commit = self._must(self._git("commit-tree", tree, *parent, "-m", message, env=who),
                            "commit-tree")
        self._must(self._git("update-ref", f"refs/heads/{BRANCH}", commit, *([head] if head
                                                                                 else [])),
                   "update-ref")
        # the repository's own index follows for this one path (the owner's other staged
        # changes stay as they were)
        self._git("update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}")
        return commit

    def log(self, limit: int = 20) -> list:
        """[(commit, author, subject)] newest first (plumbing: rev-list)."""
        if not (self.root / ".git").exists() or self.head() is None:
            return []
        r = self._git("log", f"-{int(limit)}", "--no-show-signature", "--format=%H%x00%an%x00%s")
        out = []
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            parts = line.split("\0")
            if len(parts) == 3:
                out.append(tuple(parts))
        return out
