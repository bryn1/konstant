"""The probe allowlist (DESIGN §7 step 3): a command line -> a Plan, or ValueError naming why not.

Order, never reordered: raw line has no control character; shlex split (no shell, ever); every
token refused if it holds a shell metacharacter or a `..` path segment; only THEN shape matching;
then every PATH/TREE/DB operand must realpath-resolve under the allowed roots - and never under the
workspace's var/ (board DB, tokens, run records; REVIEW F-29) - and the RESOLVED path is what runs
(REVIEW F-35). A shape is a fixed argv layout; nothing outside the table can run.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from konstant.verify.procenv import git_env, scrub_env

META_REASON = "command carries a control/shell character or a '..' path"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_META = re.compile(r"[;&|$`<>\\]")
_DOTDOT = re.compile(r"(^|/)\.\.(/|$)")

_UNIT = r"[A-Za-z0-9@._:-]{1,120}"
_NAME = r"[A-Za-z0-9._-]{1,120}"
_PATH = r"(?!-)[A-Za-z0-9@%+=,._/~-]{1,300}"
_REF = r"(?!-)[A-Za-z0-9._/^{}-]{1,200}"
_SHA = r"[0-9a-f]{7,40}"
_JOB = r"[0-9]{1,8}(\.[0-9]{1,5}){0,8}"
_COMMIT = r"(?![-/])(?!.*\.\.)(?!.*//)(?!.*[/.]$)[A-Za-z0-9._/-]{1,200}"
_SEG = r"(?!-)(?!\.\.?(?:/|$))[A-Za-z0-9@%+=,._~-]{1,255}"
_REL = rf"{_SEG}(?:/{_SEG}){{0,63}}"
_URL = r"https?://[A-Za-z0-9._:/?=%~+-]{1,300}"
_SELECT = r"(?is)\s*select\s[^;\n]{1,1000}"
_BAD_DOCKER_FMT = re.compile(r"(?i)env|json|config|secret|label")


@dataclass
class Plan:
    """What one accepted line will do. `run` is an argv for subprocess, or None for a native shape."""
    name: str
    argv: list
    run: list | None = None
    env: dict | None = None
    native: tuple | None = None
    cwd: str | None = None


@dataclass
class Roots:
    """Where operands may point, and where a relative operand starts (the workspace home)."""
    home: Path
    paths: list = field(default_factory=list)
    url_hosts: tuple = ("127.0.0.1", "localhost")

    @classmethod
    def build(cls, home, verify_cfg: dict, project_paths=()) -> "Roots":
        home = Path(home)
        extra = [p for p in project_paths if p]
        raw = list(verify_cfg.get("path_roots") or ["."]) + extra
        return cls(home, [_abs(home, r) for r in raw],
                   tuple(verify_cfg.get("url_hosts") or ("127.0.0.1", "localhost")))

    def locate(self, operand: str) -> str:
        """The resolved path to run against; ValueError if it is outside every root or in var/."""
        real = os.path.realpath(_abs(self.home, operand))
        var = os.path.realpath(Path(self.home) / "var")
        if real == var or real.startswith(var + os.sep):
            raise ValueError(f"path {operand} resolves into the workspace's var/ (board, tokens, "
                             "runs): probes never read it")
        from konstant import machinery
        for sealed in machinery.sealed(self.home):     # the holdout store, the memory vault
            s = os.path.realpath(sealed)
            if real == s or real.startswith(s + os.sep):
                raise ValueError(f"path {operand} resolves into {sealed.name}/ (a sealed path: the "
                                 "memory vault is never evidence, the holdout store never read)")
        for root in self.paths:
            r = os.path.realpath(root)
            if real == r or real.startswith(r.rstrip(os.sep) + os.sep):
                return real
        raise ValueError(f"path {operand} resolves outside the allowed roots (path_roots)")


def _abs(home: Path, operand) -> Path:
    p = Path(operand)
    return p if p.is_absolute() else Path(os.path.normpath(home / p))


def _m(rx: str, s: str) -> bool:
    return re.fullmatch(rx, s) is not None


def tokenize(cmd: str) -> list:
    """Control-char check, shlex split, per-token meta check. Runs before ANY shape matching."""
    if _CONTROL.search(cmd):
        raise ValueError(META_REASON)
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        raise ValueError(f"command does not split: {exc}") from exc
    if not argv or any(_META.search(t) or _CONTROL.search(t) or _DOTDOT.search(t) for t in argv):
        raise ValueError(META_REASON)
    return argv


def blob_spec(spec: str):
    commit, sep, path = spec.partition(":")
    if not sep or len(path) > 400 or not _m(_COMMIT, commit) or not _m(_REL, path):
        return None
    if re.fullmatch(r"[0-9a-fA-F]+", commit) and not 7 <= len(commit) <= 40:
        return None
    return commit, path


def parse_command(cmd: str, roots: Roots) -> Plan:
    argv = tokenize(cmd)
    plan = _match(argv, roots)
    if plan is None:
        raise ValueError(f"not an allowlisted read-only shape: {shlex.join(argv)[:120]}")
    return plan


def _match(a: list, roots: Roots):
    n = len(a)
    if n == 3 and a[0] == "test" and a[1] in ("-e", "-f", "-d") and _m(_PATH, a[2]):
        return _plan("test", a, roots, native=lambda p: ("test", (a[1], p)))
    if n == 3 and a[:2] == ["ls", "-ld"] and _m(_PATH, a[2]):
        return _plan("ls", a, roots, run=lambda p: ["ls", "-ld", p])
    if n == 4 and a[:2] == ["stat", "-c"] and _m(r"[%A-Za-z0-9 :./_-]{1,60}", a[2]) \
            and _m(_PATH, a[3]):
        return _plan("stat", a, roots, run=lambda p: ["stat", "-c", a[2], p])
    if n == 2 and a[0] == "sha256sum" and _m(_PATH, a[1]):
        return _plan("sha256", a, roots, run=lambda p: ["sha256sum", p])
    if n == 4 and a[:2] == ["grep", "-c"] and _m(r"(?!-)[^\x00-\x1f]{1,200}", a[2]) \
            and _m(_PATH, a[3]):
        return _plan("grep", a, roots, run=lambda p: ["grep", "-c", "-e", a[2], p])
    if n >= 5 and a[:2] == ["git", "-C"] and _m(_PATH, a[2]):
        return _git(a, roots)
    if a[:2] == ["curl", "-s"] and n in (3, 7) and _m(_URL, a[-1]):
        if n == 3 or (a[2:4] == ["-o", "/dev/null"] and a[4] == "-w" and a[5] == "%{http_code}"):
            return _curl(a, roots)
    if a[:1] == ["systemctl"]:
        return _systemctl(a)
    if n == 5 and a[:2] == ["docker", "inspect"] and a[2] in ("-f", "--format") \
            and _m(r"\{\{[^{}]{1,200}\}\}", a[3]) and not _BAD_DOCKER_FMT.search(a[3]) \
            and _m(_NAME, a[4]):
        return Plan("docker", a, run=a, env=scrub_env())
    if n == 4 and a[:2] == ["sqlite3", "-readonly"] and _m(_PATH, a[2]) and _m(_SELECT, a[3]):
        return _plan("sqlite", a, roots, native=lambda p: ("sqlite", (p, a[3])), operand=2)
    if n == 2 and a[1] == "--version" and _m(_NAME, a[0]):
        found = shutil.which(a[0])
        if found is None:
            raise ValueError(f"binary {a[0]!r} not found on PATH")
        return Plan("version", a, run=[found, "--version"], env=scrub_env(), cwd=str(roots.home))
    if n == 5 and a[:3] == ["konstant", "job", "show"] and _m(_JOB, a[3]) and a[4] == "--json":
        env = scrub_env()
        env["KONSTANT_HOME"] = str(roots.home)
        return Plan("konstant", a, env=env, cwd=str(roots.home),
                    run=[sys.executable, "-m", "konstant", "--as", "viewer", "job", "show",
                         a[3], "--json"])
    return None


def _plan(name, a, roots, run=None, native=None, operand=-1):
    path = roots.locate(a[operand])
    return Plan(name, a, run=run(path) if run else None, env=scrub_env() if run else None,
                native=native(path) if native else None, cwd=str(roots.home))


def _systemctl(a: list):
    b = a[1:]
    if b[:1] == ["--user"]:
        b = b[1:]
    ok = (len(b) == 2 and b[0] in ("is-active", "is-enabled") and _m(_UNIT, b[1])) or \
         (len(b) == 4 and b[0] == "show" and _m(_UNIT, b[1]) and b[2] == "-p"
          and _m(r"[A-Za-z]+(,[A-Za-z]+)*", b[3]))
    return Plan("systemctl", a, run=a, env=scrub_env()) if ok else None


def _curl(a: list, roots: Roots) -> Plan:
    parts = urlparse(a[-1])
    if "@" in parts.netloc or parts.hostname not in roots.url_hosts:
        raise ValueError(f"url host {parts.hostname!r} is not in [verify] url_hosts")
    if parts.path.rstrip("/").startswith("/api/memory"):
        raise ValueError("url reads the board's memory routes: memory is never evidence")
    return Plan("curl", a, native=("curl", (a[-1], len(a) == 7)))


def _git(a: list, roots: Roots):
    tree = roots.locate(a[2])
    b, n = a[3:], len(a) - 3

    def plan(run_tail, name="git", native=None):
        env = git_env()
        return Plan(name, a, run=None if native else ["git", "-C", tree, *run_tail], env=env,
                    native=native, cwd=str(roots.home))
    if b == ["rev-parse", "HEAD"]:
        return plan(b)
    if n == 3 and b[:2] == ["rev-parse", "--verify"] and _m(_REF, b[2]):
        return plan(b)
    if n == 4 and b[:2] == ["log", "-1"] and b[2] in ("--format=%H", "--format=%ae", "--format=%s") \
            and _m(_REF, b[3]):
        return plan(["log", "-1", "--no-show-signature", b[2], b[3], "--"])
    if n == 4 and b[:3] == ["branch", "-r", "--contains"] and _m(_SHA, b[3]):
        return plan(b)
    if n == 2 and b[0] == "blob-sha256" and blob_spec(b[1]):
        return plan([], name="blob", native=("blob", (tree, b[1])))
    return None
