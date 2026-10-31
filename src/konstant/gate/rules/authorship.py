"""Rule `authorship`: who wrote each verdict file (DESIGN §6.4, §6.5).

Runner mode: konstant snapshots OUT before and after every phase run and writes a manifest
(`phases/<n>-<agent>-c<cycle>.json`: created / modified / deleted files). A verdict file must be
CREATED by a run of the verifying phase it is named for and touched by no other phase run; a
verdict file written by any other phase - or by nobody konstant ran - is UNMET by name
(`AUTHORSHIP: ...`). Nothing a re-run does can undo it: a forged verdict taints the run. Each manifest also records
the sha256 of every verdict file its phase left; a verdict file whose content differs from the
sha the LAST phase that touched it recorded was changed outside every phase window (a leftover
process, a later hand edit) and is UNMET by name too (REVIEW F-05). The runner also kills every
process a phase left behind before the next phase starts (gate/reaper.py).
Interactive mode (no manifests: a person or a session drives the phases): reported once as an
unattributed WARNING, never a refusal.
"""
from __future__ import annotations

import hashlib
import json
import os

from konstant.gate.rules.common import Finding, Run, is_verdict_file, out_files, verdict_stem


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
    """A parallel group shares one snapshot: a verdict file it produced is credited by NAME to
    the member it names, so the other members' (shared) manifests do not count as writers."""
    mine = m.get("verdict") and verdict_stem(m["verdict"]) == stem
    return not mine and any(verdict_stem(v) == stem for v in m.get("group_verdicts") or [])


def check(run: Run) -> list:
    if not run.runner_mode:
        return [Finding("authorship", "AUTHORSHIP WARNING: interactive run - verdict files are "
                                      "unattributed (only `konstant task run` proves who wrote "
                                      "them)", severity="warn")]
    ms = manifests(run)
    names = set()
    for m in ms:
        for key in ("created", "modified", "deleted"):
            names |= {n for n in m.get(key) or [] if is_verdict_file(run.out / n)}
    if run.out.is_dir():
        names |= {os.path.relpath(f, run.out) for f in out_files(run.out) if is_verdict_file(f)}
    out = []
    for name in sorted(names):
        stem = verdict_stem(os.path.basename(name))
        touched = [(m, k) for m in ms for k in ("created", "modified", "deleted")
                   if name in (m.get(k) or []) and not _credited_elsewhere(m, stem)]
        own = [m for m, k in touched if k == "created" and m.get("verdict")
               and verdict_stem(m["verdict"]) == stem]
        others = [m for m, _ in touched if not (m.get("verdict")
                                                and verdict_stem(m["verdict"]) == stem)]
        label = ", ".join(f"{m.get('n')}-{m.get('agent')} (c{m.get('cycle')})" for m in others)
        if others:
            out.append(Finding("authorship", f"AUTHORSHIP: {name} was written by phase run(s) "
                                             f"{label}, not only by its verifying phase - a "
                                             "verdict is written by the phase it names, never by "
                                             "another; this run is tainted, start a new one",
                               owner="none"))
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
