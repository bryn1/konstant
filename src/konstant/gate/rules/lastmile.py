"""Rule `lastmile` (the git last mile), when the project is a git work tree and the run start is
known: no untracked file created during the run outside OUT/.audits/.tmp; no marker words
(TO-DO, FIX-ME, XXX written without the dash) added to source since the run base; every test file
changed since the base passes under pytest. Added lines come from a Python diff of the base blob
against the raw worktree file (no `git diff`: a repo filter or textconv never runs)."""
from __future__ import annotations

import difflib
import os
import re

from konstant.gate.rules.common import (Finding, Run, blob_text, git, git_top, has_run_dir,
                                        inside, worktree_drift)
from konstant.gate.rules.hygiene import is_source
from konstant.gate.rules.tests import pytest_argv, run_cmd

MARKERS = re.compile(r"\b(" + "TO" + "DO" + "|" + "FIX" + "ME" + "|" + "X" + "XX" + r")\b")
TEST_FILE = re.compile(r"(test_.*|.*_test)\.py")


def check(run: Run) -> list:
    project = run.project
    if not project or not project.is_dir() or run.start <= 0:
        return []
    top = git_top(project)
    if not top:
        return []

    def excluded(rel: str) -> bool:
        return inside(os.path.join(top, rel), run.out) or has_run_dir(rel) or rel.endswith(".pyc")

    out = []
    every = {p for p in git(top, "ls-files", "--others", "--exclude-standard", "-z")
             .stdout.split("\0") if p}
    untracked = [p for p in sorted(every) if not excluded(p)
                 and os.path.isfile(os.path.join(top, p))
                 and os.path.getmtime(os.path.join(top, p)) >= run.start]
    if untracked:
        out.append(Finding("lastmile", f"untracked file(s) created during the run in {top}: "
                                       f"{', '.join(sorted(untracked)[:10])} - commit them, or keep "
                                       "scratch under .tmp/", owner="producer"))
    base = run.rec.get("git_base")
    marks, changed = [], set(untracked)
    if base:
        changed |= {p for p in worktree_drift(top, base) if not excluded(p) and p not in every}
    for p in sorted(changed):
        full = os.path.join(top, p)
        if not is_source(p) or excluded(p) or not os.path.isfile(full):
            continue
        marks += [f"{p}: {ln.strip()[:80]}" for ln in added_lines(blob_text(top, base, p), full)
                  if MARKERS.search(ln)]
    if marks:
        out.append(Finding("lastmile", f"marker words added during the run: {'; '.join(marks[:5])}",
                           owner="producer"))
    tests = sorted(p for p in changed if not excluded(p) and os.path.isfile(os.path.join(top, p))
                   and TEST_FILE.fullmatch(os.path.basename(p)))
    if tests:
        rc, tail = run_cmd(pytest_argv(tests), top, jail_rw=(top, str(run.out)), run=run)
        if rc != 0:
            out.append(Finding("lastmile", f"changed test file(s) fail under pytest in {top} "
                                           f"(exit {rc}): {', '.join(tests[:5])}", owner="producer"))
    return out


def added_lines(before: str, path: str) -> list:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            after = fh.read().splitlines()
    except OSError:
        return []
    out = []
    sm = difflib.SequenceMatcher(None, before.splitlines(), after, autojunk=False)
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            out += after[j1:j2]
    return out
