"""Leak detection (docs/LEVEL5.md 3.5): what read prevention (3.3) cannot reach - a scenario
pasted somewhere by a person, a harness transcript nobody knew about, a hole not yet found. The
verifier runs it before any scenario.

1. Canaries: each scenario's CANARY, as raw bytes, in the project's diff base..commit (every
   added or changed blob, listed with plumbing: ls-tree + cat-file), in OUT, in every phase log
   and prompt of the job's runs, and in the job's trail -> `LEAK: canary of H2 found in <path>`.
2. Literals: a distinctive literal (>= 4 chars, not in the brief) of RUN or of the expectation
   on an ADDED line of that diff -> `LEAK-SUSPECT: ...` (a hard-coded expected answer is what
   teaching to the test produces). The line names the scenario and the file, never the literal.
The commitment check (store file hash = the board's sha256) is the verifier's own step.
"""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path

from konstant.holdout import lint
from konstant.verify import holdout as runner

SCAN_CAP = 8 * 1024 * 1024          # a bigger file is scanned in its first 8 MiB


def changed(project, base, commit: str) -> list:
    """[(path, old bytes, new bytes)] of every blob added or changed from base to commit."""
    new = {p: o for _m, o, p in runner.tree(project, commit)}
    old = {p: o for _m, o, p in runner.tree(project, base)} if base else {}
    paths = sorted(p for p, o in new.items() if old.get(p) != o)
    data = runner.blobs(project, list(dict.fromkeys(
        [new[p] for p in paths] + [old[p] for p in paths if p in old])))
    return [(p, data[old[p]] if p in old else b"", data[new[p]]) for p in paths]


def added_lines(old: bytes, new: bytes) -> list:
    a = old.decode("utf-8", "replace").splitlines()
    b = new.decode("utf-8", "replace").splitlines()
    return [ln[1:] for ln in difflib.unified_diff(a, b, lineterm="", n=0)
            if ln.startswith("+") and not ln.startswith("+++")]


def _files(root: Path):
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x != ".git")
        for fn in sorted(files):
            yield Path(d) / fn


def _read(path: Path) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(SCAN_CAP)
    except OSError:
        return b""


def run_sources(ws: Path, runs: list) -> list:
    """[(label, bytes)]: OUT files, phase logs and prompts of the job's runs. Only run dirs
    directly under <workspace>/var/runs/ are read (the check's trust rule, F-06)."""
    out, base = [], os.path.realpath(Path(ws) / "var" / "runs")
    for rd in dict.fromkeys(str(r) for r in runs):
        real = os.path.realpath(rd)
        if os.path.dirname(real) != base or not os.path.isdir(real):
            continue
        name = os.path.basename(real)
        for sub in ("phases", "prompts"):
            for f in _files(Path(real) / sub):
                out.append((f"var/runs/{name}/{sub}/{f.name}", _read(f)))
        try:
            rec = json.loads((Path(real) / "record.json").read_text())
            o = Path(rec["out"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if o.is_dir():
            for f in _files(o):
                out.append((f"OUT {f.relative_to(o)} (run {name})", _read(f)))
    return out


def canaries(scenarios: list, sources: list) -> list:
    """LEAK lines: (label, bytes) sources searched for each canary as raw bytes."""
    out = []
    for sc in scenarios:
        mark = sc.canary.encode()
        for label, data in sources:
            if mark in data:
                out.append(f"LEAK: canary of {sc.hid} found in {label}")
    return out


def suspects(scenarios: list, diff: list, brief: str) -> list:
    out = []
    for sc in scenarios:
        lits = [x for x in lint.literals(sc) if x not in (brief or "")]
        for path, old, new in diff:
            lines = added_lines(old, new)
            if any(x in ln for x in lits for ln in lines):
                out.append(f"LEAK-SUSPECT: a literal of {sc.hid} appears on an added line of "
                           f"{path}")
    return out


def scan(ws, scenarios: list, *, project, base, commit, runs: list, trail: list,
         brief: str) -> tuple:
    """(LEAK lines, LEAK-SUSPECT lines)."""
    diff = changed(project, base, commit)
    sources = [(path, new) for path, _old, new in diff]
    sources += run_sources(Path(ws), runs)
    sources += [(f"trail row {t.get('id')}", json.dumps(t).encode()) for t in trail]
    return canaries(scenarios, sources), suspects(scenarios, diff, brief)
