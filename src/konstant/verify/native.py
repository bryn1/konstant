"""Probe shapes evaluated inside this process instead of by an external program.

`test`, `curl`, `sqlite3` and `blob-sha256` never reach a shell or another binary: each returns
(rc, output) from Python. Every function is bounded by a timeout and the 64 KiB output cap.
"""
from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from konstant.verify.procenv import git_env

OUTPUT_CAP = 64 * 1024


def exists(flag: str, path: str) -> tuple[int, str]:
    """`test -e|-f|-d PATH`: the verdict is the exit code, so the row carries `ok` / `absent`."""
    p = Path(path)
    hit = {"-e": p.exists, "-f": p.is_file, "-d": p.is_dir}[flag]()
    return (0, "ok\n") if hit else (1, "absent\n")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def curl(url: str, code_only: bool, timeout: float) -> tuple[int, str]:
    """`curl -s [-o /dev/null -w %{http_code}] URL`: one GET, redirects not followed."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "konstant-verify"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            code, body = resp.status, resp.read(OUTPUT_CAP)
    except urllib.error.HTTPError as exc:
        code, body = exc.code, exc.read(OUTPUT_CAP)
    except (urllib.error.URLError, OSError) as exc:
        if isinstance(getattr(exc, "reason", exc), TimeoutError) or isinstance(exc, TimeoutError):
            raise TimeoutError from None
        return 7, f"curl: could not connect: {getattr(exc, 'reason', exc)}\n"
    if code_only:
        return 0, str(code)
    return 0, body.decode("utf-8", "replace")


def _cell(value) -> str:
    return "" if value is None else str(value)


def _read_only(action, arg1, arg2, db, source):
    ok = action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION)
    return sqlite3.SQLITE_OK if ok else sqlite3.SQLITE_DENY


def sqlite_select(db: str, sql: str, timeout: float) -> tuple[int, str]:
    """`sqlite3 -readonly DB "SELECT ..."`: read-only URI, only SELECT/READ/FUNCTION allowed."""
    uri = "file:" + urllib.parse.quote(db) + "?mode=ro"
    deadline = time.monotonic() + timeout
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=min(timeout, 5))
    except sqlite3.Error as exc:
        return 1, f"Error: unable to open database {db}: {exc}\n"
    try:
        conn.set_authorizer(_read_only)
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        try:
            rows = conn.execute(sql).fetchall()
        except sqlite3.Error as exc:
            if "interrupted" in str(exc):
                raise TimeoutError from None
            return 1, f"Error: {exc}\n"
    finally:
        conn.close()
    return 0, "".join("|".join(_cell(c) for c in row) + "\n" for row in rows)


def blob_sha256(tree: str, spec: str, timeout: float) -> tuple[int, str]:
    """`git -C TREE blob-sha256 REV:PATH`: sha256 of the COMMITTED blob, git plumbing only."""
    rev, _, path = spec.partition(":")
    env = git_env()
    head = subprocess.run(["git", "-C", tree, "rev-parse", "--verify", "-q", rev + "^{commit}"],
                          capture_output=True, text=True, env=env, timeout=timeout,
                          stdin=subprocess.DEVNULL)
    sha = head.stdout.strip()
    if head.returncode != 0 or len(sha) != 40:
        return 5, f"unknown commit {rev}\n"
    blob = subprocess.run(["git", "-C", tree, "cat-file", "blob", f"{sha}:{path}"],
                          capture_output=True, env=env, timeout=timeout,
                          stdin=subprocess.DEVNULL)
    if blob.returncode != 0:
        return 5, f"{sha}:{path} is not a blob\n"
    return 0, f"sha256: {hashlib.sha256(blob.stdout).hexdigest()}  {sha}:{path}\n"
