"""The run record `var/runs/<stamp>-<slug>/record.json` (DESIGN §6.3): everything the DoD check
needs to judge the run from the run dir alone - type, phases, verdict files, flags, OUT, the git
base of the project, the start epoch, the job, the [gate] settings in force, the judge command."""
from __future__ import annotations

import json
import re
import shlex
import sys
import time
from pathlib import Path

from konstant.gate.rules.common import git_head, git_top

VERSION = 1


def slugify(task: str) -> str:
    text = re.sub(r"\[type:[^\]]*\]", " ", task.lower())
    words = re.findall(r"[a-z0-9]+", text)[:6]
    return ("-".join(words) or "task")[:40].strip("-") or "task"


def konstant_cmd(*args) -> str:
    return shlex.join([sys.executable, "-m", "konstant", *map(str, args)])


def new_run_dir(home: Path, task: str, now: float | None = None) -> tuple:
    """(run dir, stamp, slug); created, never reused."""
    now = time.time() if now is None else now
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    slug = slugify(task)
    base = Path(home) / "var" / "runs"
    base.mkdir(parents=True, exist_ok=True)
    for i in range(1000):
        d = base / (f"{stamp}-{slug}" + (f"-{i}" if i else ""))
        try:
            d.mkdir()
            return d, stamp, slug
        except FileExistsError:
            continue
    raise RuntimeError(f"cannot create a run dir under {base}")


def default_out(project, run_dir: Path, stamp: str, slug: str) -> Path:
    if project:
        return Path(project) / ".audits" / f"{stamp}-{slug}" / "out"
    return run_dir / "out"


GATE_KEYS = ("max_cycles", "max_resumes", "test_cmd", "cleanup", "hygiene", "jail")


def catalog_fields(cat, ttype: str, gate_cfg: dict) -> dict:
    """The record fields that come from the catalog and the workspace config. `task check`
    re-derives exactly these instead of trusting a record (REVIEW F-06, F-11)."""
    return {
        "phases": [dict(p, n=i) for i, p in enumerate(cat.phases(ttype), 1)],
        "read_only": cat.read_only(ttype),
        "done_rows": ({"negative": True, "surfaces": cat.surfaces()}
                      if cat.done_rows(ttype) else {}),
        "exercise": cat.done_rows(ttype),
        "verdict_words": cat.verdict_words(),
        "gate": {k: gate_cfg[k] for k in GATE_KEYS if k in gate_cfg},
    }


def build(cat, task: str, ttype: str, why: str, *, run_dir: Path, out: Path, project,
          workspace: Path, job, mode: str, gate_cfg: dict, start: float | None = None) -> dict:
    project = str(Path(project).resolve()) if project else None
    top = git_top(project) if project else None
    rec = {
        "version": VERSION, "task": task, "type": ttype, "why": why, "mode": mode,
        **catalog_fields(cat, ttype, gate_cfg),
        "out": str(Path(out).resolve()), "project": project, "workspace": str(workspace),
        "git_top": top, "git_base": git_head(top) if top else None,
        "start": time.time() if start is None else start, "job": job,
        "run_dir": str(run_dir),
    }
    rec["judge_cmd"] = konstant_cmd("task", "judge", "--run", run_dir)
    rec["check_cmd"] = konstant_cmd("task", "check", run_dir)
    return rec


def write(run_dir: Path, rec: dict) -> Path:
    Path(rec["out"]).mkdir(parents=True, exist_ok=True)
    path = Path(run_dir) / "record.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path
