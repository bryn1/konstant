"""A manifest of konstant's composition machinery, so a factory run cannot compose from a catalog
a phase edited (REVIEW L5-R1 H-06).

F-08 made the runner snapshot each agent's profile at run start, which stops a phase from steering
LATER phases of the SAME run. It does not stop a level-4 `command` phase (unjailed under the
closed profile) from editing `catalog/` on disk, because every LATER run - factory runs included -
composes its prompts from that catalog. `catalog/` is in machinery.DIRS (no jailed phase writes
it), but a closed level-4 phase is not jailed.

So `konstant agents sync` records the sha256 of every file under `catalog/` in
`var/machinery.json`, and every factory run and `konstant doctor` REFUSE (FAIL) when the catalog
on disk differs from the manifest. The only way to change the catalog without a FAIL is to run
`agents sync` again, which re-reads the catalog deliberately and re-records it. A level-4 phase's
edit therefore stops the next factory run instead of steering its verifying phases.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

MANIFEST = "var/machinery.json"
SCHEMA = 1


def _catalog_root(cfg) -> Path:
    from konstant import catalog as catalog_mod
    return Path(catalog_mod.find_root(cfg.home, cfg.data["catalog"]["path"]))


def catalog_digest(cfg) -> dict:
    """{catalog-relative path: sha256} of every file under catalog/ (sorted, symlinks skipped)."""
    root = _catalog_root(cfg)
    out = {}
    if not root.is_dir():
        return out
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        for name in sorted(files):
            p = Path(d) / name
            if p.is_symlink() or not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def manifest_path(cfg) -> Path:
    return cfg.home / MANIFEST


def record(cfg) -> dict:
    """Write the manifest from the catalog on disk (called by `agents sync`: a deliberate read)."""
    data = {"schema": SCHEMA, "catalog": catalog_digest(cfg)}
    p = manifest_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, indent=0), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    return data


def load(cfg) -> dict | None:
    try:
        data = json.loads(manifest_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "catalog" in data else None


def drift(cfg) -> list:
    """[] when the catalog matches the manifest; else the differing paths ('changed/added/removed:
    <rel>'). A missing manifest returns ['no manifest'] (fail closed: record one with `agents
    sync`)."""
    man = load(cfg)
    if man is None:
        return ["no manifest"]
    want = man.get("catalog") or {}
    have = catalog_digest(cfg)
    out = []
    for rel in sorted(set(want) | set(have)):
        if rel not in have:
            out.append(f"removed: {rel}")
        elif rel not in want:
            out.append(f"added: {rel}")
        elif want[rel] != have[rel]:
            out.append(f"changed: {rel}")
    return out


def require(cfg) -> str | None:
    """None when a factory run may compose from this catalog; else the reason it must not (the
    drift, or the missing manifest). The caller refuses the run (exit 2)."""
    d = drift(cfg)
    if not d:
        return None
    if d == ["no manifest"]:
        return ("konstant's machinery manifest is missing (var/machinery.json): run "
                "`bin/konstant agents sync` to record it before a factory run")
    head = ", ".join(d[:4]) + (" ..." if len(d) > 4 else "")
    return (f"catalog/ changed outside `agents sync` ({head}): a factory run will not compose "
            "from a catalog a phase may have edited (REVIEW L5-R1 H-06); if the change is "
            "intended, run `bin/konstant agents sync` to re-record it")


def doctor_row(cfg) -> tuple:
    """(status, "machinery", detail) for `konstant doctor`: FAIL when catalog/ drifted from the
    manifest `agents sync` recorded (REVIEW L5-R1 H-06)."""
    d = drift(cfg)
    if not d:
        return ("PASS", "machinery", "catalog/ matches var/machinery.json (`agents sync`): a "
                "factory run composes only from the recorded catalog")
    if d == ["no manifest"]:
        return ("WARN", "machinery", "no catalog manifest: `bin/konstant agents sync` records it "
                "(a factory run refuses without it)")
    head = ", ".join(d[:4]) + (" ..." if len(d) > 4 else "")
    return ("FAIL", "machinery", f"catalog/ changed outside `agents sync` ({head}): re-record "
            "with `agents sync` if intended (factory runs refuse until then)")
