"""Rule `judged` and the judge command behind `konstant task judge` (DESIGN §6.4).

A verifying phase runs the judge command as its LAST step and puts the printed
`# JUDGED: <sha256>` line directly above its verdict line. The sha is the content hash of THE
DELIVERABLE STATE, a sorted {key: sha256} map of
  out/<rel>   every file under OUT except verdict files, DONE.md, CYCLES.md, HANDOFF.md, scratch
              (.tmp, .audits) and caches;
  git/<rel>   when the project is a git work tree: every path outside OUT whose RAW content
              differs from the run's base commit (committed or not) plus untracked, not-ignored
              files (common.worktree_drift: no repo filter or textconv ever runs);
  proj/<rel>  when the project is NOT a git work tree: every file under the project outside OUT
              (there is no base to diff against, so the whole tree is the state).
Content-based on purpose: `touch` changes nothing; an edit, add, delete or revert does.
The judge saves the full map and the EXACT args it hashed with under OUT/.tmp/judged/. The check
REPLAYS those args: a pin with no recorded args is UNMET (PIN-ARGS-UNRECORDED), a pin judged
against another base than the record's is UNMET (PIN-BASE-DIFFERS), a different hash means the
deliverable changed after it was judged. An EMPTY state is refused: a pin over nothing pins nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from konstant.gate.rules.common import (CACHE_DIRS, META_NAMES, RUN_DIRS, Finding, Run, git,
                                        git_head, git_top, has_run_dir, inside, is_verdict_file,
                                        out_files, worktree_drift)
from konstant.gate.rules.verdicts import decisive, judged_line, words


class JudgeRefused(Exception):
    pass


def _sha(path) -> str:
    if os.path.islink(path):
        return "link:" + hashlib.sha256(os.readlink(path).encode()).hexdigest()
    if not os.path.isfile(path):
        return "deleted"
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def out_state(out: Path) -> dict:
    state = {}
    if not out.is_dir():
        return state
    for f in out_files(out):
        if f.name.lower() in META_NAMES or is_verdict_file(f):
            continue
        state["out/" + os.path.relpath(f, out)] = _sha(f)
    return state


def _git_drift(top: str, base, out: Path) -> dict:
    if base and git(top, "rev-parse", "--verify", "-q", base + "^{commit}").returncode != 0:
        raise JudgeRefused(f"base {base[:12]} is not a commit in {top}")
    base = base or git_head(top)
    state = {}
    for rel in worktree_drift(top, base):
        full = os.path.join(top, rel)
        if inside(full, out) or has_run_dir(rel) or rel.endswith(".pyc"):
            continue
        state["git/" + rel] = _sha(full)
    return state


def _tree(project: Path, out: Path, since=None) -> dict:
    state = {}
    for root, dirs, files in os.walk(project):
        dirs[:] = sorted(d for d in dirs if d not in CACHE_DIRS and d not in RUN_DIRS)
        for fn in sorted(files):
            full = os.path.join(root, fn)
            if fn.endswith(".pyc") or inside(full, out):
                continue
            if since is not None and os.path.getmtime(full) < since:
                continue
            state["proj/" + os.path.relpath(full, project)] = _sha(full)
    return state


def project_state(args: dict, since=None) -> dict:
    """The project part of the state for these args (record or recorded pin args).
    `since` (non-git projects only) keeps files modified at/after it: "did the run change it"."""
    project, out = args.get("project"), Path(args["out"])
    if not project or not os.path.isdir(project):
        return {}
    top = git_top(project)
    if top:
        return _git_drift(top, args.get("git_base"), out)
    return _tree(Path(project), out, since)


def state_of(args: dict) -> dict:
    return {**out_state(Path(args["out"])), **project_state(args)}


def digest(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def pin_args(rec: dict) -> dict:
    return {"out": rec["out"], "project": rec.get("project"), "git_base": rec.get("git_base")}


def judge(rec: dict) -> str:
    """Compute, save (map + args) and return the pin for a record. Raises JudgeRefused."""
    args = pin_args(rec)
    state = state_of(args)
    if not state:
        raise JudgeRefused(f"EMPTY deliverable state for {args['out']}: no file under OUT and no "
                           "project change - a pin over nothing pins nothing")
    sha = digest(state)
    d = Path(args["out"]) / ".tmp" / "judged"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sha}.json").write_text(json.dumps(state, indent=0, sort_keys=True))
    (d / f"{sha}.args.json").write_text(json.dumps(args, sort_keys=True))
    return sha


def _load(out: Path, name: str):
    try:
        return json.loads((out / ".tmp" / "judged" / name).read_text())
    except (OSError, ValueError):
        return None


def changed_paths(old: dict, new: dict) -> list:
    return [p for p in sorted(set(old) | set(new)) if old.get(p) != new.get(p)]


def check(run: Run) -> list:
    out, cache = [], {}
    passing = words(run)["pass"]
    from konstant.gate.rules.common import verdict_word
    for vf, f in decisive(run).items():
        if verdict_word(f) not in passing:
            continue
        owner = f"verifier:{vf}"
        sha = judged_line(f)
        if sha is None:
            out.append(Finding("judged", f"{f.name} carries no single '# JUDGED: <sha>' line - the "
                                         f"verifying phase runs `{run.rec.get('judge_cmd')}` as its "
                                         "last step and puts the printed line above its verdict",
                               owner=owner))
            continue
        args = _load(run.out, f"{sha}.args.json")
        if not isinstance(args, dict):
            out.append(Finding("judged", f"PIN-ARGS-UNRECORDED: {f.name} pins {sha[:12]} but no "
                                         "args were recorded for that pin - re-run the judge "
                                         "command, never hand-roll a hash", owner=owner))
            continue
        if args.get("git_base") != run.rec.get("git_base") or args.get("project") != \
                run.rec.get("project") or args.get("out") != run.rec.get("out"):
            out.append(Finding("judged", f"PIN-BASE-DIFFERS: {f.name} was judged with base "
                                         f"{args.get('git_base')} / project {args.get('project')} "
                                         f"but the run's are {run.rec.get('git_base')} / "
                                         f"{run.rec.get('project')}", owner=owner))
            continue
        key = json.dumps(args, sort_keys=True)
        if key not in cache:
            try:
                st = state_of(args)
            except JudgeRefused as exc:
                out.append(Finding("judged", f"cannot recompute {f.name}'s pin: {exc}", owner=owner))
                continue
            cache[key] = (st, digest(st))
        st, now = cache[key]
        if now != sha:
            old = _load(run.out, f"{sha}.json")
            what = (", ".join(changed_paths(old, st)[:8]) if isinstance(old, dict)
                    else "(no map saved)")
            out.append(Finding("judged", f"{f.name} judged a different deliverable state (JUDGED "
                                         f"{sha[:12]}, now {now[:12]}): changed since - {what}",
                               owner=owner))
    return out
