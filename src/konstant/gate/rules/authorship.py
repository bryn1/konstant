"""Rule `authorship`: who wrote each verdict file (DESIGN §6.4, §6.5).

Runner mode: konstant snapshots OUT before and after every phase run and writes a manifest
(`phases/<n>-<agent>-c<cycle>.json`: created / modified / deleted files). A verdict file must be
CREATED by the phase run konstant named it for (the manifest's `verdict`: the catalog's name,
cycle suffixed - not a stem match, L5-L2) and touched by no other phase run; a
verdict file written by any other phase - or by nobody konstant ran - is UNMET by name
(`AUTHORSHIP: ...`). Nothing a re-run does can undo it: a forged verdict taints the run. Each manifest also records
the sha256 of every verdict file its phase left; a verdict file whose content differs from the
sha the LAST phase that touched it recorded was changed outside every phase window (a leftover
process, a later hand edit) and is UNMET by name too (REVIEW F-05). The runner also kills every
process a phase left behind before the next phase starts (gate/reaper.py).
A verdict file is a *verdict*.md file DIRECTLY in OUT (common.is_verdict_file): konstant reads
a phase's verdict only from there. A scoped verifier's private OUT/verify-<stem>/ (DESIGN 6.4)
holds its evidence, whatever the file names (L5-L2): what proves it is the verifier's is WHO
wrote it, not a name, so every file there created, modified or deleted by a phase run other than
its owner is UNMET by name (`AUTHORSHIP:`, owner none) - the jail already refuses such a write,
the manifests prove it on a harness without the jail too. Inside a parallel group (one shared
snapshot) a private-dir file is credited to the dir's owner, a verdict file to the member
konstant named it for.
Interactive mode (no manifests: a person or a session drives the phases): reported once as an
unattributed WARNING, never a refusal.
"""
from __future__ import annotations

import hashlib
import json
import os

from konstant.gate.rules.common import (Finding, Run, is_verdict_file, out_files, private_owner,
                                        verdict_stem)


def _seq(path) -> tuple:
    head = path.name.split("-", 1)[0]
    return (int(head) if head.isdigit() else 0, path.name)


def manifests(run: Run) -> list:
    d = run.run_dir / "phases"
    out = []
    for p in sorted(d.glob("*.json"), key=_seq) if d.is_dir() else []:
        try:
            m = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(m, dict):
            m["_file"] = p.name
            out.append(m)
    return out


def _credited_elsewhere(m: dict, stem: str) -> bool:
    """A parallel group shares one snapshot: what it produced in a private dir is credited by the
    dir to the member that owns it, so the other members' (shared) manifests do not count."""
    mine = m.get("verdict") and verdict_stem(m["verdict"]) == stem
    return not mine and any(verdict_stem(v) == stem for v in m.get("group_verdicts") or [])


def _target(m: dict, name: str) -> bool:
    """`name` is the verdict file konstant told this phase run to write (its manifest's
    `verdict`, cycle suffixed): the identity of a verdict is konstant's, never a name a phase
    picked (L5-L2: a stem match let a phase write another cycle's file of its own verdict)."""
    return bool(m.get("verdict")) and not m.get("closeout") and m["verdict"] == name


def _group_target(m: dict, name: str) -> bool:
    """In a parallel group a verdict file is credited to the member konstant named it for."""
    return not _target(m, name) and name in (m.get("group_verdicts") or [])


def check(run: Run) -> list:
    if not run.runner_mode:
        return [Finding("authorship", "AUTHORSHIP WARNING: interactive run - verdict files are "
                                      "unattributed (only `konstant task run` proves who wrote "
                                      "them)", severity="warn")]
    ms = manifests(run)
    names = set()
    for m in ms:
        for key in ("created", "modified", "deleted"):
            names |= {n for n in m.get(key) or [] if is_verdict_file(n)}
    if run.out.is_dir():
        names |= {os.path.relpath(f, run.out) for f in out_files(run.out)
                  if is_verdict_file(f, run.out)}
    out = private_writers(run, ms)
    for name in sorted(names):
        touched = [(m, k) for m in ms for k in ("created", "modified", "deleted")
                   if name in (m.get(k) or []) and not _group_target(m, name)]
        own = [m for m, k in touched if k == "created" and _target(m, name)]
        others = [m for m, _ in touched if not _target(m, name)]
        label = ", ".join(_label(m) for m in others)
        if others:
            out.append(Finding("authorship", f"AUTHORSHIP: {name} was written by phase run(s) "
                                             f"{label}, not only by the phase run konstant named "
                                             "it for - a verdict is written by the phase it "
                                             "names, never by another; this run is tainted, start "
                                             "a new one", owner="none"))
        elif not own:
            out.append(Finding("authorship", f"AUTHORSHIP: {name} was not created by any phase "
                                             "run konstant started - a verdict file written "
                                             "outside the runner proves nothing", owner="none"))
        else:
            out += _changed_after(run, name, ms)
    return out


def _changed_after(run: Run, name: str, ms: list) -> list:
    """The sha the last phase that touched `name` recorded must still be its content."""
    last = [m for m in ms if name in (m.get("shas") or {})]
    if not last:
        return []
    want = last[-1]["shas"][name]
    try:
        now = hashlib.sha256((run.out / name).read_bytes()).hexdigest()
    except OSError:
        now = "missing"
    if now == want:
        return []
    return [Finding("authorship", f"AUTHORSHIP: {name} changed after phase run "
                                  f"{last[-1].get('label')} ended (recorded {want[:12]}, now "
                                  f"{now[:12]}) - only its phase writes a verdict, inside its own "
                                  "window; this run is tainted, start a new one", owner="none")]


def private_writers(run: Run, ms: list) -> list:
    """Every file of a private dir OUT/verify-<stem>/ is its owner's: a phase run that is not the
    owner's verifying phase (by the verdict konstant told it to write, never by a file name) and
    touched one taints the run."""
    own_dirs = run.rec.get("own_dirs") or []
    bad: dict = {}
    for m in ms if own_dirs else []:
        for key in ("created", "modified", "deleted"):
            for name in m.get(key) or []:
                owner = private_owner(name, own_dirs)
                if owner is None:
                    continue
                stem = verdict_stem(owner)
                mine = m.get("verdict") and not m.get("closeout") and \
                    verdict_stem(os.path.basename(m["verdict"])) == stem
                if mine or _credited_elsewhere(m, stem):
                    continue
                bad.setdefault(name, []).append(m)
    return [Finding("authorship", f"AUTHORSHIP: {name} lies in the private dir of "
                                  f"{private_owner(name, own_dirs)} but was written by phase "
                                  f"run(s) {', '.join(sorted({_label(m) for m in who}))} - only its "
                                  "verifier writes there; this run is tainted, start a new one",
                    owner="none") for name, who in sorted(bad.items())]


def _label(m: dict) -> str:
    return f"{m.get('n')}-{m.get('agent')} (c{m.get('cycle')})"
