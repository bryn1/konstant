"""The job hierarchy (pure sqlite, no FastAPI).

  depth 0  project root  created by `project add`, type `project`, never closes, carries no DoD
  depth 1  feature       carries the DoD
  depth 2  task          only when a feature needs more than one session
Depth > 2 is refused, at filing and on a move.

display_id is DERIVED at read time and is the full path from the root: "<root id>.<seq>.<seq>",
seq = 1-based rank by id among siblings. Nothing stores a display id, so a move needs no rewrite;
the path of a sibling can shift, and `move` reports which ones did. resolve_path() also accepts
the old one-level form "<parent id>.<seq>": the first segment is always a raw id.
"""
from __future__ import annotations

from typing import Optional

MAX_DEPTH = 2
_HOP_LIMIT = 64          # safety valve against a corrupt parent_id cycle


class TreeRefused(Exception):
    """A placement the hierarchy rules forbid. `code` is the HTTP status to answer with."""

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _row(conn, job_id: int):
    return conn.execute("SELECT id, parent_id, project_id, title FROM jobs WHERE id=?",
                        (int(job_id),)).fetchone()


def ancestors(conn, job_id: int) -> list:
    """[parent, grandparent, ..., root] ids of job_id."""
    out, seen, cur = [], {int(job_id)}, _row(conn, job_id)
    while cur is not None and cur["parent_id"] is not None:
        pid = int(cur["parent_id"])
        if pid in seen or len(out) >= _HOP_LIMIT:
            raise TreeRefused(f"parent_id cycle present at job {pid}", 409)
        out.append(pid)
        seen.add(pid)
        cur = _row(conn, pid)
    return out


def depth(conn, job_id: int) -> int:
    return len(ancestors(conn, job_id))


def descendants(conn, job_id: int) -> set:
    out, frontier = set(), [int(job_id)]
    while frontier:
        q = "SELECT id FROM jobs WHERE parent_id IN (%s)" % ",".join("?" * len(frontier))
        frontier = [r[0] for r in conn.execute(q, frontier).fetchall() if r[0] not in out]
        out.update(frontier)
    return out


def subtree_height(conn, job_id: int) -> int:
    """0 for a leaf, 1 with children, 2 with grandchildren."""
    height, level, frontier = 0, 0, [int(job_id)]
    while frontier and level < _HOP_LIMIT:
        q = "SELECT id FROM jobs WHERE parent_id IN (%s)" % ",".join("?" * len(frontier))
        frontier = [r[0] for r in conn.execute(q, frontier).fetchall()]
        level += 1
        if frontier:
            height = level
    return height


def _seq(conn, parent_id: int, job_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM jobs WHERE parent_id=? AND id<=?",
                        (int(parent_id), int(job_id))).fetchone()[0]


def display_id(conn, job_id: int) -> str:
    job_id = int(job_id)
    try:
        chain = ancestors(conn, job_id)
    except TreeRefused:
        return str(job_id)
    if not chain:
        return str(job_id)
    lineage = [job_id] + chain                     # self, parent, ..., root
    parts = [str(lineage[-1])]
    for child, parent in zip(reversed(lineage[:-1]), reversed(lineage[1:])):
        parts.append(str(_seq(conn, parent, child)))
    return ".".join(parts)


def resolve_path(conn, raw) -> Optional[int]:
    """A raw id or a display id -> the internal id, or None. Malformed input is never a guess."""
    s = str(raw if raw is not None else "").strip()
    if not s or any(not p.isdigit() for p in s.split(".")):
        return None
    parts = [int(p) for p in s.split(".")]
    cur = parts[0]
    if len(parts) == 1:
        row = conn.execute("SELECT id FROM jobs WHERE id=?", (cur,)).fetchone()
        return row[0] if row else None
    for seq in parts[1:]:
        if seq < 1:
            return None
        row = conn.execute("SELECT id FROM jobs WHERE parent_id=? ORDER BY id LIMIT 1 OFFSET ?",
                           (cur, seq - 1)).fetchone()
        if row is None:
            return None
        cur = row[0]
    return cur


def check_new_child(conn, parent_id: int) -> int:
    """Depth the new job would sit at under parent_id; raises TreeRefused beyond MAX_DEPTH."""
    parent = _row(conn, parent_id)
    if parent is None:
        raise TreeRefused(f"parent {parent_id} not found", 404)
    new_depth = depth(conn, parent_id) + 1
    if new_depth > MAX_DEPTH:
        raise TreeRefused(
            f"depth > 2: job {parent_id} is a task (depth {new_depth - 1}) and cannot have "
            "children; the hierarchy is project root -> feature -> task. File the job under "
            "its feature instead.", 422)
    return new_depth


def validate_move(conn, job_id: int, new_parent_id: int) -> dict:
    job_id, new_parent_id = int(job_id), int(new_parent_id)
    job, parent = _row(conn, job_id), _row(conn, new_parent_id)
    if job is None:
        raise TreeRefused(f"job {job_id} not found", 404)
    if parent is None:
        raise TreeRefused(f"parent {new_parent_id} not found", 404)
    if job["parent_id"] is None:
        raise TreeRefused(f"job {job_id} is a project root; a root is never moved", 409)
    if job_id == new_parent_id:
        raise TreeRefused(f"job {job_id} cannot be its own parent", 409)
    if new_parent_id in descendants(conn, job_id):
        raise TreeRefused(f"cycle: parent {new_parent_id} is below job {job_id}", 409)
    if parent["project_id"] != job["project_id"]:
        raise TreeRefused(f"parent {new_parent_id} belongs to another project", 409)
    new_depth = depth(conn, new_parent_id) + 1
    bottom = new_depth + subtree_height(conn, job_id)
    if bottom > MAX_DEPTH:
        raise TreeRefused(f"depth > 2: job {job_id} would sit at depth {new_depth} with a "
                          f"subtree reaching depth {bottom}; the cap is {MAX_DEPTH}", 422)
    return {"job_id": job_id, "from_parent_id": job["parent_id"],
            "to_parent_id": new_parent_id, "depth": new_depth,
            "noop": job["parent_id"] == new_parent_id}


def affected(conn, job_id: int, parents) -> set:
    out = {int(job_id)} | descendants(conn, job_id)
    for p in parents:
        if p is not None:
            out |= descendants(conn, p)
    return out
