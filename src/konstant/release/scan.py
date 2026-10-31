"""Public-safety scan (DESIGN §11): nothing that identifies a private deployment ships.

Two sources of patterns:
- `release/patterns.toml` (ships): generic shapes - IPv4 outside loopback/documentation ranges,
  email addresses outside example domains, token shapes, private-key headers, assigned secrets,
  absolute home/server paths, internal ticket references.
- a denylist (maintainer-local, git-ignored and export-ignored): one case-insensitive regex per
  line (`#` comments and blank lines skipped; a line that is not a valid regex is matched
  literally). A denylist finding is reported by its line number, never by the term, so the
  report itself names nothing.

`scan --tree DIR`: in a git work tree the files are the tracked + untracked-not-ignored ones minus
`export-ignore` paths (= what `git archive` would ship); elsewhere every file under DIR. Files
with a NUL byte in their first 8 KiB are binary and skipped (counted in the report).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

try:  # Python >= 3.11
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as _toml

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}


class ScanError(Exception):
    """The scan could not run (missing or malformed pattern file, unreadable denylist)."""


@dataclass
class Pattern:
    name: str
    regex: re.Pattern
    allow: tuple = ()

    def findings(self, text: str):
        for m in self.regex.finditer(text):
            if not any(a.fullmatch(m.group(0)) for a in self.allow):
                yield m


@dataclass
class Finding:
    path: str
    line: int
    pattern: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.pattern}"


@dataclass
class Result:
    files: int
    binary: int
    patterns: int
    denylist_terms: int | None          # None = denylist skipped
    findings: list

    @property
    def clean(self) -> bool:
        return not self.findings


def default_patterns_path() -> Path:
    here = Path(__file__).resolve().parents[3] / "release" / "patterns.toml"
    for cand in (Path.cwd() / "release" / "patterns.toml", here):
        if cand.is_file():
            return cand
    raise ScanError("release/patterns.toml not found (run from the source tree or pass "
                    "--patterns PATH)")


def load_patterns(path: Path) -> list:
    try:
        data = _toml.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, _toml.TOMLDecodeError) as exc:
        raise ScanError(f"{path}: {exc}") from exc
    out = []
    for name, spec in (data.get("patterns") or {}).items():
        try:
            out.append(Pattern(name, re.compile(spec["regex"]),
                               tuple(re.compile(a) for a in spec.get("allow", []))))
        except (KeyError, re.error) as exc:
            raise ScanError(f"{path}: pattern {name!r}: {exc}") from exc
    if not out:
        raise ScanError(f"{path}: no [patterns.*] defined")
    return out


def load_denylist(path: Path) -> list:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ScanError(f"denylist {path}: {exc.strerror or exc}") from exc
    return load_denylist_lines(lines)


def load_denylist_lines(lines: list) -> list:
    out = []
    for n, raw in enumerate(lines, 1):
        term = raw.strip()
        if not term or term.startswith("#"):
            continue
        try:
            rx = re.compile(term, re.I)
        except re.error:
            rx = re.compile(re.escape(term), re.I)
        out.append(Pattern(f"denylist:{n}", rx))
    return out


def tree_files(root: Path) -> list:
    """Relative paths under ROOT that would ship (git-aware, see module doc)."""
    root = Path(root).resolve()
    git = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if git.returncode == 0 and Path(git.stdout.strip()).resolve() == root:
        ls = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                             "--exclude-standard"], capture_output=True, check=True)
        files = sorted({f for f in ls.stdout.decode().split("\0") if f and (root / f).is_file()})
        # a directory pattern (`.github/ export-ignore`) is set on ".github/", not on the
        # files inside, so every parent directory is asked too
        dirs = {str(Path(f).parents[i]) + "/" for f in files for i in range(len(Path(f).parts) - 1)}
        asked = files + sorted(dirs)
        attr = subprocess.run(["git", "-C", str(root), "check-attr", "-z", "export-ignore",
                               "--stdin"], input="\0".join(asked).encode(), capture_output=True,
                              check=True).stdout.decode().split("\0")
        ignored = {attr[i] for i in range(0, len(attr) - 2, 3) if attr[i + 2] == "set"}
        return [f for f in files if f not in ignored
                and not any(str(par) + "/" in ignored for par in Path(f).parents)]
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and not (set(rel.parts) & SKIP_DIRS):
            out.append(str(rel))
    return out


def scan_text(rel: str, text: str, patterns: list) -> list:
    found = []
    starts = [0] + [i + 1 for i, c in enumerate(text) if c == "\n"]
    for pat in patterns:
        for m in pat.findings(text):
            line = _line_of(starts, m.start())
            found.append(Finding(rel, line, pat.name))
    return found


def _line_of(starts: list, pos: int) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def scan_files(root: Path, files: list, patterns: list, denylist: list | None) -> Result:
    root = Path(root)
    pats = patterns + (denylist or [])
    findings, binary = [], 0
    for rel in files:
        # the path itself (line 0): a file named after a host or person is a finding too
        findings += [Finding(rel, 0, f.pattern) for f in scan_text(rel, rel, pats)]
        raw = (root / rel).read_bytes()
        if b"\0" in raw[:8192]:
            binary += 1
            continue
        findings += scan_text(rel, raw.decode("utf-8", errors="replace"), pats)
    findings.sort(key=lambda f: (f.path, f.line, f.pattern))
    return Result(files=len(files), binary=binary, patterns=len(patterns),
                  denylist_terms=None if denylist is None else len(denylist), findings=findings)


def report(res: Result, header: list | None = None) -> str:
    lines = list(header or [])
    lines += [f"FILES_SCANNED: {res.files} ({res.binary} binary skipped)",
              f"PATTERNS: {res.patterns}",
              "DENYLIST: SKIPPED" if res.denylist_terms is None
              else f"DENYLIST_TERMS: {res.denylist_terms}"]
    lines += [f"FINDING: {f}" for f in res.findings]
    lines.append("RESULT: CLEAN" if res.clean else f"RESULT: FINDINGS ({len(res.findings)})")
    return "\n".join(lines) + "\n"
