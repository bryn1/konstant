"""The local target of a ship (docs/LEVEL5.md 5.1, 2.4): the project repository the job clones
are made from. After a github or branch ship it moves too (compare-and-swap), so the next job's
clone starts from the shipped state. When its checked-out branch is the ship branch, konstant
rewrites the changed paths of its worktree itself from raw objects of the ship repository (no
checkout, no filter, no hook), refusing beforehand a worktree with local changes on tracked or
shipped paths and a branch checked out in a linked worktree."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from konstant.factory import shiprepo
from konstant.factory.shiprepo import ShipRepoError


def _checked_out(target: Path, ref: str) -> bool:
    r = shiprepo.run(target, "symbolic-ref", "-q", "HEAD")
    bare = shiprepo.run(target, "rev-parse", "--is-bare-repository").stdout.strip() == b"true"
    return not bare and r.returncode == 0 and r.stdout.decode().strip() == ref


def _linked_worktrees(target: Path, ref: str) -> list:
    wt = shiprepo.git_dir(target) / "worktrees"
    out = []
    for d in sorted(wt.iterdir()) if wt.is_dir() else []:
        try:
            if (d / "HEAD").read_text().strip() == f"ref: {ref}":
                out.append(d.name)
        except OSError:
            pass
    return out


def local_tip(target: Path, ref: str) -> str:
    return shiprepo.out(target, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")


def local_checks(target: Path, ref: str, pre: str, paths: list) -> list:
    from konstant.factory.shiprules import bad, ok
    from konstant.gate.rules.common import base_tree, worktree_drift
    try:
        tip = local_tip(target, ref)
    except ShipRepoError:
        head = shiprepo.run(target, "symbolic-ref", "-q", "--short", "HEAD").stdout.decode().strip()
        return [bad("target", f"the target {target} has no branch {ref.split('/', 2)[-1]} (its "
                              f"checked-out branch is {head or 'detached'}): name the ship branch "
                              "in the goal's [ship] branch or [factory] defaults ship_branch")]
    if tip != pre:
        return [bad("base", f"target moved: expected {pre}, {target} {ref} is at {tip}")]
    if _linked_worktrees(target, ref):
        return [bad("worktree", f"{ref} is checked out in a linked worktree of {target}: "
                                "konstant would leave it stale")]
    if _checked_out(target, ref):
        tracked = base_tree(str(target), pre)
        dirty = [p for p in worktree_drift(str(target), pre) if p in tracked or p in paths]
        if dirty:
            return [bad("worktree", f"target worktree has local changes ({', '.join(dirty[:5])}):"
                                    " commit or remove them first")]
    return [ok("base", f"{target} {ref} is at the clone's base {pre[:12]}")]


def _safe_path(root: Path, rel: str) -> Path:
    """`root/rel` when no component is `..`/`.git` and no existing parent is a symlink (checked
    before anything is created, so a planted link never redirects a write)."""
    parts = rel.split("/")
    if rel.startswith("/") or ".." in parts or ".git" in (p.lower() for p in parts):
        raise ShipRepoError(f"tree path {rel!r} leaves the worktree or writes into .git")
    cur = Path(os.path.realpath(root))
    for name in parts[:-1]:
        cur = cur / name
        if os.path.islink(cur) or (os.path.exists(cur) and not os.path.isdir(cur)):
            raise ShipRepoError(f"tree path {rel!r} runs through a symlink or a file")
    cur.mkdir(parents=True, exist_ok=True)
    return cur / parts[-1]


def _remove(full: Path) -> None:
    if os.path.islink(full) or (os.path.lexists(full) and not os.path.isdir(full)):
        os.unlink(full)
    elif os.path.isdir(full):
        shutil.rmtree(full)


def sync_worktree(repo: Path, target: Path, old: str, new: str) -> None:
    """Rewrite the paths that differ between `old` and `new` in the target's worktree from raw
    objects of the ship repository, then the index (read-tree): no checkout, filter or hook.
    Deletions first (a directory may become a file), then the new content."""
    rows = shiprepo.changes(repo, old, new)
    root = Path(os.path.realpath(target))
    for st, rel, *_r in rows:
        if st != "D":
            continue
        full = _safe_path(root, rel)
        _remove(full)
        d = full.parent
        while d != root and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent
    blobs = shiprepo.read_batch(repo, [r[3] for r in rows if r[0] != "D"])
    for st, rel, _oo, no, mode in rows:
        if st == "D":
            continue
        full = _safe_path(root, rel)
        _remove(full)
        data = blobs[no][1]
        if mode == "120000":
            os.symlink(data, full)
            continue
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o755 if mode == "100755" else 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    shiprepo.out(target, "read-tree", new)


def move_local(repo: Path, target: Path, ref: str, old: str, new: str) -> None:
    """Objects first, then the compare-and-swap, then (checked out) the worktree."""
    shiprepo.transfer(repo, target, new)
    shiprepo.update_ref(target, ref, new, old)
    if _checked_out(target, ref):
        sync_worktree(repo, target, old, new)
