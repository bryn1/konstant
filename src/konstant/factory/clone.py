"""Job clones (docs/LEVEL5.md 2.4): a factory job's phases never touch the TARGET (the project's
canonical repository). At the job's first claim the board records `<project path>@<job id>` and
the target commit it starts from (`jobs.workdir`, `jobs.workdir_base`); the runner then makes the
clone here, with plumbing only (F-04): `git init` without templates (no hooks), the target's
object store as an alternate (read-only reuse, nothing copied), the branch ref set with
`update-ref`, the tree written by konstant itself from `ls-tree`/`cat-file` (no checkout, no
filter, no attribute, no hook runs) and the index built with `read-tree`. Every git command runs
under the pinned environment of gate/rules/common.py (no system/global config, no hooks path, no
fsmonitor, no transport).

The clone is the run's project: the phases work and commit there, the DoD check and the verifier
judge it, and the target stays read-only in every phase jail (the jail binds only the clone, OUT
and the phase's own dirs writable)."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from konstant.gate.rules.common import git

MARKER = "konstant-clone.json"          # in the clone's .git/: target + base, for re-claims


class CloneError(Exception):
    """A clone that cannot be made or reused: the run stops (exit 2), never falls back."""


def workdir_of(project_path: str, job_id: int) -> str:
    """The clone of job `job_id` beside its project: `<project path>@<job id>` (the board stores
    the same form as the project's own path: workspace-relative or absolute)."""
    return f"{str(project_path).rstrip('/')}@{int(job_id)}"


def target_tip(target) -> str:
    """The commit the target's checked-out branch points at (plumbing: rev-parse)."""
    if not (Path(target) / ".git").exists():
        raise CloneError(f"{target} is not a git repository: a job with sealed holdouts runs on "
                         "a clone of its project's commit")
    r = git(target, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    sha = r.stdout.strip()
    if r.returncode != 0 or not sha:
        raise CloneError(f"{target} has no commit yet: a job clone starts from one")
    return sha


def _branch(target) -> str:
    r = git(target, "symbolic-ref", "-q", "--short", "HEAD")
    name = r.stdout.strip()
    return name if r.returncode == 0 and name else "main"


def _objects(target) -> str:
    r = git(target, "rev-parse", "--git-common-dir")
    common = r.stdout.strip()
    if r.returncode != 0 or not common:
        raise CloneError(f"cannot find the object store of {target}")
    path = common if os.path.isabs(common) else os.path.join(str(target), common)
    return os.path.realpath(os.path.join(path, "objects"))


def _must(r, what: str) -> None:
    if r.returncode != 0:
        raise CloneError(f"{what} failed: {(r.stderr or r.stdout).strip()[-300:]}")


def read_marker(dest) -> dict | None:
    try:
        return json.loads((Path(dest) / ".git" / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def create(target, dest, base: str) -> str:
    """Make (or reuse) the clone `dest` of `target` at `base`. Returns "created" or "kept".
    A later claim of the same job keeps the clone (its work continues from its own commits; the
    base stays the one recorded at the first claim). Anything else at `dest` is refused."""
    from konstant.verify.holdout import HoldoutError, materialise
    target, dest = Path(target), Path(dest)
    if dest.exists():
        mark = read_marker(dest)
        if mark and mark.get("base") == base and \
                os.path.realpath(mark.get("target", "")) == os.path.realpath(target):
            return "kept"
        raise CloneError(f"{dest} exists and is not this job's clone of {target} at {base[:12]}: "
                         "move it away, konstant never overwrites it")
    branch, objects = _branch(target), _objects(target)
    dest.mkdir(parents=True)
    try:
        _must(git(dest, "init", "-q", "--template="), "git init of the clone")
        info = dest / ".git" / "objects" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "alternates").write_text(objects + "\n", encoding="utf-8")
        _must(git(dest, "update-ref", f"refs/heads/{branch}", base), "update-ref")
        _must(git(dest, "symbolic-ref", "HEAD", f"refs/heads/{branch}"), "symbolic-ref")
        try:
            materialise(dest, base, dest)
        except HoldoutError as exc:
            raise CloneError(f"cannot write the tree of {base[:12]}: {exc}") from None
        _must(git(dest, "read-tree", base), "read-tree")
        git(dest, "update-index", "-q", "--refresh")
        (dest / ".git" / MARKER).write_text(json.dumps(
            {"target": str(target), "base": base, "branch": branch}) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return "created"
