"""Rule `licence` (docs/CONCEPTS.md "Triage"; the table: konstant/triage/licence.py). UNEXCUSABLE.

Copied code needs a recorded compatible licence. The run declares each copy as a row in DONE.md or
OUT/LICENSES.md:

    COPIED | <path in the project or OUT> | <source: URL or repository> | <SPDX licence id>

  - every COPIED row needs a path, a source and a licence konstant knows that is compatible with
    the project's own licence (LICENSE / pyproject.toml / package.json / Cargo.toml), else UNMET;
  - a file this run added or changed whose ADDED lines show an outside source - a "copied /
    adapted / ported / taken / vendored / derived from <source>" note, an
    `SPDX-License-Identifier:` other than the project's, or the URL of one of this run's research
    sources (var/research/<run>/result.json) - needs a COPIED row for that file, else UNMET.
Only code and configuration files are scanned (a document that cites a source is not a copy).
Owner: producer (the copy, or its row, is the deliverable's). konstant checks declarations and
provenance marks; it does not detect a silent copy without any mark (stated in CONCEPTS).
"""
from __future__ import annotations

import os
import re

from konstant.gate.rules.common import (Finding, Run, blob_text, git_top, has_run_dir, inside,
                                        out_files, worktree_drift)
from konstant.gate.rules.done import cells
from konstant.triage import licence

ROW_FILES = ("DONE.md", "LICENSES.md", "LICENCES.md")
MARK = re.compile(r"(?i)\b(?:copied|adapted|ported|taken|borrowed|vendored|derived|lifted)\s+"
                  r"from\s*:?\s+(?P<src>https?://[^\s)\"'>]+|[\w.-]+/[\w./-]+)")
TEXT_EXT = re.compile(r"\.(py|ts|tsx|js|jsx|mjs|cjs|go|rs|java|kt|c|h|cc|cpp|hpp|rb|"
                      r"php|sh|bash|ya?ml|toml|json|sql|html|css|scss|vue|svelte|swift|cs|lua|"
                      r"ex|exs|tf|cfg|ini)$", re.I)


def rows(run: Run) -> list:
    """[(path, source, licence, file)] of the COPIED rows."""
    out = []
    for name in ROW_FILES:
        f = run.out / name
        if not f.is_file():
            continue
        for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if "|" not in line:
                continue
            cs = cells(line)
            if cs and cs[0].strip("*`_ ").upper() == "COPIED":
                cs = (cs + ["", "", ""])[:4]
                out.append((cs[1].strip("`* "), cs[2].strip("`* "), cs[3].strip("`* "), name))
    return out


def research_urls(run: Run) -> list:
    from konstant.triage import research
    res = research.load_result(run.workspace or run.run_dir.parent.parent.parent, run.run_dir)
    srcs = ((res or {}).get("parsed") or {}).get("sources") or []
    return [s["url"] for s in srcs if len(s.get("url", "")) >= 12]


def changed(run: Run) -> list:
    """[(display path, added lines)] of the files this run added or changed: project files vs the
    run base (plumbing, as rule lastmile) and the source files in OUT (all their lines)."""
    out = []
    for f in out_files(run.out):
        rel = os.path.relpath(f, run.out)
        if TEXT_EXT.search(f.name) and f.name not in ROW_FILES and "verdict" not in f.name.lower():
            try:
                out.append((rel, f.read_text(encoding="utf-8", errors="ignore").splitlines()))
            except OSError:
                pass
    project = run.project
    top = git_top(project) if project and project.is_dir() else None
    base = run.rec.get("git_base")
    if top and base:
        from konstant.gate.rules.lastmile import added_lines
        for rel in worktree_drift(top, base):
            full = os.path.join(top, rel)
            if (has_run_dir(rel) or inside(full, run.out) or not os.path.isfile(full)
                    or not TEXT_EXT.search(rel)):
                continue
            out.append((rel, added_lines(blob_text(top, base, rel), full)))
    return out


def _covered(path: str, declared: list) -> bool:
    p = path.replace(os.sep, "/").lstrip("./")
    for d in declared:
        d = d.replace(os.sep, "/").lstrip("./")
        if d and (p == d or p.endswith("/" + d) or d.endswith("/" + p)):
            return True
    return False


def check(run: Run) -> list:
    proj_lic, where = licence.project_licence(run.project) if run.project else (None, "no project")
    out, declared = [], []
    for path, src, lic, fname in rows(run):
        if not path or not src:
            out.append(Finding("licence", f"{fname}: a COPIED row needs `COPIED | <path> | "
                                          "<source> | <licence>`", owner="producer"))
            continue
        declared.append(path)
        ok, why = licence.compatible(lic, proj_lic)
        if not ok:
            out.append(Finding("licence", f"LICENCE: {path} copied from {src[:120]}: {why} "
                                          f"(project licence {proj_lic or 'unknown'}, {where}); "
                                          "remove the copy or copy from a compatible source",
                               owner="producer"))
    urls = research_urls(run)
    for rel, lines in changed(run):
        if _covered(rel, declared):
            continue
        why = ""
        for ln in lines:
            m = MARK.search(ln)
            if m:
                why = f"a provenance note ({m.group(0)[:80]})"
                break
            s = licence.SPDX.search(ln)
            if s and licence.normalise(s.group(1)) != proj_lic:
                why = f"an SPDX-License-Identifier {s.group(1)}"
                break
            u = next((u for u in urls if u in ln), None)
            if u:
                why = f"a research source URL ({u[:80]})"
                break
        if why:
            out.append(Finding("licence", f"LICENCE: {rel} shows {why} but no `COPIED | {rel} | "
                                          "<source> | <SPDX licence>` row records its licence "
                                          "(DONE.md or OUT/LICENSES.md)", owner="producer"))
    return out
