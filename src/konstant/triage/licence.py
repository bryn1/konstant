"""Licences of copied code (docs/CONCEPTS.md "Triage"; the DoD rule gate/rules/licence.py).

Code a run copies from elsewhere (a page the researcher found, another repository) needs a
recorded licence that is compatible with the project's own, or the DoD check refuses it. konstant
does not judge originality: it reads what the run declares (`COPIED | <path> | <source> |
<SPDX id>` rows in DONE.md or OUT/LICENSES.md) and the provenance a copy leaves in the added lines
(a "copied/adapted/ported from <source>" note, an `SPDX-License-Identifier:` line, a URL of the
run's own research sources), and it checks the declared licence against a small fixed table.

The table (deterministic, conservative; not legal advice, and the docs say so):
  - a permissive source (MIT, BSD, ISC, Apache-2.0, ...) goes into any project, except
    Apache-2.0 into a GPL-2.0-only one (the patent and termination terms clash);
  - a copyleft source goes only into a project under the same licence or one the source's own
    terms allow (GPL-2.0-or-later -> GPL-3.0, LGPL -> GPL/AGPL of the same or a later version,
    GPL-3.0 -> AGPL-3.0, MPL-2.0 -> its secondary licences: GPL/LGPL/AGPL);
  - an unknown, missing or proprietary licence is never compatible;
  - a project whose own licence konstant cannot read takes permissive sources only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PERMISSIVE = ("MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense",
              "CC0-1.0", "Zlib", "BSL-1.0", "Apache-2.0", "PSF-2.0", "Python-2.0", "X11",
              "BlueOak-1.0.0", "Unicode-3.0")
COPYLEFT = ("LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
            "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
            "AGPL-3.0-only", "AGPL-3.0-or-later", "MPL-2.0", "EPL-2.0")
UNKNOWN = ("unknown", "none", "proprietary", "NOASSERTION", "all-rights-reserved")
KNOWN = PERMISSIVE + COPYLEFT
ALIASES = {
    "mit license": "MIT", "the mit license": "MIT", "expat": "MIT",
    "apache 2.0": "Apache-2.0", "apache-2": "Apache-2.0", "apache2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "apache license, version 2.0": "Apache-2.0",
    "bsd": "BSD-3-Clause", "bsd-3": "BSD-3-Clause", "new bsd": "BSD-3-Clause",
    "bsd-2": "BSD-2-Clause", "simplified bsd": "BSD-2-Clause",
    "gpl-2.0": "GPL-2.0-only", "gplv2": "GPL-2.0-only", "gpl-2.0+": "GPL-2.0-or-later",
    "gpl-3.0": "GPL-3.0-only", "gplv3": "GPL-3.0-only", "gpl-3.0+": "GPL-3.0-or-later",
    "lgpl-2.1": "LGPL-2.1-only", "lgpl-3.0": "LGPL-3.0-only", "agpl-3.0": "AGPL-3.0-only",
    "agplv3": "AGPL-3.0-only", "mpl 2.0": "MPL-2.0", "public domain": "Unlicense",
    "cc0": "CC0-1.0", "psf": "PSF-2.0",
}
# copyleft source -> the project licences its own terms allow (besides its own id)
INTO = {
    "GPL-2.0-or-later": ("GPL-2.0-only", "GPL-3.0-only", "GPL-3.0-or-later", "AGPL-3.0-only",
                         "AGPL-3.0-or-later"),
    "GPL-3.0-only": ("AGPL-3.0-only", "AGPL-3.0-or-later"),
    "GPL-3.0-or-later": ("GPL-3.0-only", "AGPL-3.0-only", "AGPL-3.0-or-later"),
    "LGPL-2.1-only": ("GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later"),
    "LGPL-2.1-or-later": ("LGPL-3.0-only", "LGPL-3.0-or-later", "GPL-2.0-only",
                          "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
                          "AGPL-3.0-only", "AGPL-3.0-or-later"),
    "LGPL-3.0-only": ("GPL-3.0-only", "GPL-3.0-or-later", "AGPL-3.0-only", "AGPL-3.0-or-later"),
    "LGPL-3.0-or-later": ("LGPL-3.0-only", "GPL-3.0-only", "GPL-3.0-or-later", "AGPL-3.0-only",
                          "AGPL-3.0-or-later"),
    "AGPL-3.0-or-later": ("AGPL-3.0-only",),
    "MPL-2.0": ("GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later", "LGPL-2.1-or-later",
                "LGPL-3.0-only", "LGPL-3.0-or-later", "AGPL-3.0-only", "AGPL-3.0-or-later"),
}


def normalise(value: str):
    """The SPDX id for `value`, `unknown` for a value that names no licence konstant knows."""
    v = (value or "").strip().strip("`*_\"' ")
    if not v:
        return "unknown"
    for k in KNOWN + UNKNOWN:
        if v.lower() == k.lower():
            return k
    return ALIASES.get(v.lower(), "unknown")


def compatible(source: str, project) -> tuple:
    """(ok, why) for code under `source` copied into a project under `project` (None: unread)."""
    src = normalise(source)
    if src in UNKNOWN:
        return False, f"source licence {source.strip() or 'missing'!r} is not a known licence"
    if src in PERMISSIVE:
        if src == "Apache-2.0" and project == "GPL-2.0-only":
            return False, "Apache-2.0 code cannot go into a GPL-2.0-only project"
        return True, f"{src} is permissive"
    if project is None:
        return False, (f"{src} is copyleft and the project's own licence is unknown (konstant "
                       "read no LICENSE, pyproject.toml, package.json or Cargo.toml licence)")
    if src == project or project in INTO.get(src, ()):
        return True, f"{src} code may go into a {project} project"
    return False, f"{src} code cannot go into a {project} project"


PHRASES = (
    (re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 3", re.I), "AGPL-3.0-only"),
    (re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 3", re.I), "LGPL-3.0-only"),
    (re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 2\.1", re.I),
     "LGPL-2.1-only"),
    (re.compile(r"GNU GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 3", re.I), "GPL-3.0-only"),
    (re.compile(r"GNU GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 2", re.I), "GPL-2.0-only"),
    (re.compile(r"Mozilla Public License,? [Vv]ersion 2\.0"), "MPL-2.0"),
    (re.compile(r"Apache License[\s\S]{0,80}Version 2\.0", re.I), "Apache-2.0"),
    (re.compile(r"Permission is hereby granted, free of charge", re.I), "MIT"),
    (re.compile(r"free and unencumbered software released into the public domain", re.I),
     "Unlicense"),
    (re.compile(r"Permission to use, copy, modify, and/or distribute this software for any "
                r"purpose with or without fee", re.I), "ISC"),
    (re.compile(r"Redistribution and use in source and binary forms[\s\S]*Neither the name",
                re.I), "BSD-3-Clause"),
    (re.compile(r"Redistribution and use in source and binary forms", re.I), "BSD-2-Clause"),
    (re.compile(r"CC0 1\.0 Universal", re.I), "CC0-1.0"),
)
SPDX = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+-]+)")


def project_licence(root) -> tuple:
    """(SPDX id or None, where it was read)."""
    if not root:
        return None, "no project"
    root = Path(root)
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "COPYING"):
        f = root / name
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")[:20000]
        m = SPDX.search(text)
        if m and normalise(m.group(1)) != "unknown":
            return normalise(m.group(1)), name
        for rx, lic in PHRASES:
            if rx.search(text):
                return lic, name
    for name, rx in (("pyproject.toml", r'(?m)^\s*license\s*=\s*(?:\{\s*text\s*=\s*)?"([^"]+)"'),
                     ("Cargo.toml", r'(?m)^\s*license\s*=\s*"([^"]+)"')):
        f = root / name
        if f.is_file():
            m = re.search(rx, f.read_text(encoding="utf-8", errors="replace"))
            if m and normalise(m.group(1)) != "unknown":
                return normalise(m.group(1)), name
    f = root / "package.json"
    if f.is_file():
        try:
            lic = json.loads(f.read_text(encoding="utf-8")).get("license")
        except (ValueError, AttributeError):
            lic = None
        if isinstance(lic, str) and normalise(lic) != "unknown":
            return normalise(lic), "package.json"
    return None, "no licence file konstant can read"
