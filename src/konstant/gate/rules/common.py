"""Shared pieces of the DoD rules: the run context, findings, OUT walking, verdict files.

A Finding names its rule, the phase that owns the fix (the loop resumes that phase) and a
one-line reason. Owners: "producer" (the deliverable), "orchestrator" (DONE.md, CYCLES.md),
"verifier:<VERDICT FILE>" (that verifying phase), "none" (nothing a re-run can fix).
Severity "unmet" -> exit 3, "blocked" -> exit 4, "warn" -> stderr only.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

META_NAMES = {"done.md", "cycles.md", "handoff.md"}
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".git", "node_modules", ".venv", "venv",
              ".mypy_cache", ".ruff_cache", ".tox"}
RUN_DIRS = {".audits", ".tmp"}
VERDICT_LINE = re.compile(r"^#\s*VERDICT:\s*(\S+)\s*$")
CYCLE_RE = re.compile(r"-c(\d+)\.md$", re.I)


@dataclass
class Finding:
    rule: str
    text: str
    owner: str = "orchestrator"
    severity: str = "unmet"

    def line(self) -> str:
        return ("BLOCKED: " + self.text) if self.severity == "blocked" else self.text


@dataclass
class Run:
    """Everything a rule may read: the run record and what it points at."""
    run_dir: Path
    rec: dict
    catalog: object = None
    board: object = None          # BoardView or None: verified + DECLINED refs
    offline: bool = False         # `task check --offline`: no board reads (rule verified skipped)
    env: dict = field(default_factory=dict)
    workspace: object = None      # the workspace whose var/runs holds this run (check.load_run)

    @property
    def out(self) -> Path:
        return Path(self.rec["out"])

    @property
    def start(self) -> float:
        try:
            v = float(self.rec.get("start") or 0)
        except (TypeError, ValueError):
            return 0.0
        return v if v > 0 and v == v else 0.0

    @property
    def project(self):
        p = self.rec.get("project")
        return Path(p) if p else None

    @property
    def gate(self) -> dict:
        return self.rec.get("gate") or {}

    @property
    def verifying(self) -> list:
        return [p for p in self.rec.get("phases", []) if p.get("verdict")]

    @property
    def runner_mode(self) -> bool:
        return self.rec.get("mode") == "runner"


def out_files(out: Path):
    """Every file under OUT except run/scratch dirs and caches."""
    for root, dirs, files in os.walk(out):
        dirs[:] = sorted(d for d in dirs if d not in CACHE_DIRS and d not in RUN_DIRS
                         and not d.startswith(".tmp-"))
        for fn in sorted(files):
            if not fn.endswith(".pyc"):
                yield Path(root) / fn


def verdict_named(name: str) -> bool:
    """*verdict*.md (case-insensitive): the NAME of a verdict file. A name alone proves nothing."""
    low = name.lower()
    return low.endswith(".md") and "verdict" in low


def is_verdict_file(path, out=None) -> bool:
    """A verdict file is a *verdict*.md file DIRECTLY in OUT: OUT's top level is konstant's verdict
    namespace (every adapter and the dsh plugin write a phase's verdict there, and konstant reads
    a phase's verdict only from `OUT/<its catalog name, cycle suffixed>`). `path` is relative to
    OUT, or absolute with `out` given. A file in a subdirectory - a verifier's private
    OUT/verify-<stem>/ included - is evidence or deliverable whatever its name: never read as a
    verdict, in every pin that covers its place (L5-L2: a closing architect's
    `verify-arch/a5-verdict-prejudge.md`, written where its prompt told it to put its evidence,
    was taken for a forged verdict and ended the attempt). Forging and shadowing stay refused by
    the authorship rule: every top-level verdict-named file must be created by the phase it
    names, and a private dir is written only by its owner (gate/rules/authorship.py)."""
    p = Path(path)
    if out is not None and p.is_absolute():
        try:
            p = p.relative_to(out)
        except ValueError:
            return False
    return len(p.parts) == 1 and verdict_named(p.name)


def own_dir(verdict: str) -> str:
    """The private OUT dir of a scoped verifying phase: TEST-verdict.md -> verify-test."""
    return "verify-" + verdict_stem(os.path.basename(verdict)).lower()


def private_owner(rel: str, own_dirs) -> str | None:
    """The verdict file whose private dir holds `rel` (a path relative to OUT), else None."""
    parts = Path(rel).parts
    if len(parts) < 2:
        return None
    return next((v for v in own_dirs or () if own_dir(v) == parts[0]), None)


def verdict_stem(name: str) -> str:
    """TEST-verdict.md / TEST-verdict-c2.md -> "TEST"."""
    return name.split("-verdict", 1)[0].upper() if "-verdict" in name.lower() else name.upper()


def cycle_of(name: str) -> int:
    m = CYCLE_RE.search(name)
    return int(m.group(1)) if m else 1


def cycle_name(verdict_file: str, cycle: int) -> str:
    """The file a verifying phase writes in cycle N: TEST-verdict.md, TEST-verdict-c2.md, ..."""
    return verdict_file if cycle <= 1 else verdict_file[:-3] + f"-c{cycle}.md"


def lines_of(path: Path) -> list:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [ln.rstrip("\n") for ln in fh if ln.strip()]


def verdict_word(path: Path):
    """The word of the LAST line when it is a verdict line, else None."""
    try:
        lines = lines_of(path)
    except OSError:
        return None
    m = VERDICT_LINE.match(lines[-1].strip()) if lines else None
    return m.group(1).upper() if m else None


# Every git command konstant itself runs is isolated from configuration a repo (or an agent that
# edited it) controls: no system/global config, no fsmonitor, no hooks, no transport, no pager, and
# no command that converts worktree content (clean filters, textconv): worktree drift is hashed
# by konstant itself (worktree_drift), never by `git diff`/`git status` (REVIEW F-04).
GIT_ISOLATION = ("-c", "safe.directory=*", "-c", "core.fsmonitor=false", "-c",
                 "core.hooksPath=/dev/null", "-c", "protocol.allow=never", "-c",
                 "core.untrackedCache=false", "-c", "core.attributesFile=/dev/null")


def git_env(base: dict | None = None) -> dict:
    from konstant import tools
    env = tools.env(base)                         # PATH = konstant's trusted dirs (REVIEW H-01)
    for k in [k for k in env if k.startswith(("GIT_CONFIG_", "GIT_DIR", "GIT_WORK_TREE",
                                              "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                                              "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                                              "GIT_CEILING_DIRECTORIES"))]:
        env.pop(k)                    # konstant's view of a project never takes the caller's
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM="1", GIT_PAGER="cat",
               GIT_NO_REPLACE_OBJECTS="1")
    return env


def git(top, *args, timeout: int = 120) -> subprocess.CompletedProcess:
    from konstant import tools
    return subprocess.run([tools.git(), *GIT_ISOLATION, "-C", str(top), *args],
                          capture_output=True, text=True, errors="replace", timeout=timeout,
                          env=git_env(), stdin=subprocess.DEVNULL)


def _z(out: str) -> list:
    return [p for p in out.split("\0") if p]


def blob_id(path: str, algo: str = "sha1") -> str:
    """The git blob id of the RAW content (a symlink: its target), as `hash-object --no-filters`."""
    data = os.readlink(path).encode() if os.path.islink(path) else Path(path).read_bytes()
    h = hashlib.new(algo)
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def base_tree(top: str, base: str) -> dict:
    """{path: (mode, object id)} of every entry of the base commit (plumbing: ls-tree)."""
    out = {}
    for item in _z(git(top, "ls-tree", "-r", "-z", "--full-tree", base).stdout):
        meta, _, path = item.partition("\t")
        parts = meta.split()
        if len(parts) == 3:
            out[path] = (parts[0], parts[2])
    return out


def worktree_drift(top: str, base) -> list:
    """Paths whose worktree content differs from the base commit (added, modified, deleted), plus
    untracked files that are not ignored. Content-based on the RAW bytes: `touch` changes nothing
    and no repo-configured filter, textconv or hook is ever run (git only lists names and ids)."""
    algo = "sha256" if git(top, "rev-parse", "--show-object-format").stdout.strip() == "sha256" \
        else "sha1"
    tree = base_tree(top, base) if base else {}
    index = set(_z(git(top, "ls-files", "-z").stdout))
    untracked = set(_z(git(top, "ls-files", "--others", "--exclude-standard", "-z").stdout))
    out = []
    for rel in sorted(set(tree) | index | untracked):
        full = os.path.join(top, rel)
        entry = tree.get(rel)
        if entry and entry[0] == "160000":             # a submodule: its own repository
            continue
        present = os.path.lexists(full)
        if entry is None:
            if present and not os.path.isdir(full):
                out.append(rel)
        elif not present or (os.path.isdir(full) and not os.path.islink(full)):
            out.append(rel)
        else:
            try:
                if blob_id(full, algo) != entry[1]:
                    out.append(rel)
            except OSError:
                out.append(rel)
    return out


def blob_text(top: str, base, rel: str) -> str:
    """The base commit's content of `rel` ('' when absent): `cat-file blob`, no textconv."""
    if not base:
        return ""
    r = git(top, "cat-file", "blob", f"{base}:{rel}")
    return r.stdout if r.returncode == 0 else ""


def git_top(path) -> str | None:
    p = Path(path).absolute()
    while not p.is_dir() and p != p.parent:
        p = p.parent
    try:
        r = git(p, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def git_head(top) -> str | None:
    if not top:
        return None
    r = git(top, "rev-parse", "--verify", "-q", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def inside(path, parent) -> bool:
    p, q = os.path.realpath(path), os.path.realpath(parent)
    return p == q or p.startswith(q + os.sep)


def has_run_dir(rel: str) -> bool:
    return bool(set(rel.replace(os.sep, "/").split("/")) & (RUN_DIRS | CACHE_DIRS))
