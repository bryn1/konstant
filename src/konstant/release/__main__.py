"""`python -m konstant.release build|scan|clidoc` - maintainer tooling (DESIGN §11)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from konstant.release import build as build_mod
from konstant.release import clidoc, scan


def _build(a) -> int:
    if not a.denylist and not a.no_denylist:
        print("konstant release: a denylist is required (--denylist PATH); pass --no-denylist "
              "to build without one (recorded as DENYLIST: SKIPPED)", file=sys.stderr)
        return 2
    try:
        ok, text = build_mod.build(Path(a.root), a.version, None if a.no_denylist else
                                   Path(a.denylist), dist=Path(a.dist) if a.dist else None,
                                   worktree=a.worktree)
    except (build_mod.BuildError, scan.ScanError) as exc:
        print(f"konstant release: {exc}", file=sys.stderr)
        return 1
    print(text, end="")
    return 0 if ok else 1


def _scan(a) -> int:
    try:
        pats = scan.load_patterns(Path(a.patterns) if a.patterns else
                                  scan.default_patterns_path())
        deny = scan.load_denylist(Path(a.denylist)) if a.denylist else None
        root = Path(a.tree)
        res = scan.scan_files(root, scan.tree_files(root), pats, deny)
    except scan.ScanError as exc:
        print(f"konstant release: {exc}", file=sys.stderr)
        return 2
    print(scan.report(res, [f"TREE: {a.tree}"]), end="")
    return 0 if res.clean else 1


def _clidoc(a) -> int:
    text = clidoc.render()
    if a.write:
        clidoc.target().write_text(text, encoding="utf-8")
        print(f"wrote {clidoc.target()}")
    else:
        print(text, end="")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m konstant.release",
                                description="konstant maintainer tooling: release build, "
                                            "public-safety scan, CLI reference")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build dist/konstant-V.tar.gz, scan it, write .sha256")
    b.add_argument("--version", required=True)
    b.add_argument("--denylist", help="maintainer-local denylist (one regex per line)")
    b.add_argument("--no-denylist", action="store_true", help="build without one (recorded)")
    b.add_argument("--worktree", action="store_true",
                   help="archive the current files instead of a clean HEAD")
    b.add_argument("--root", default=".", help="source tree (default: .)")
    b.add_argument("--dist", help="output dir (default: <root>/dist)")
    b.set_defaults(func=_build)
    s = sub.add_parser("scan", help="scan a tree for identifying names, addresses and secrets")
    s.add_argument("--tree", required=True)
    s.add_argument("--denylist")
    s.add_argument("--patterns", help="patterns.toml (default: release/patterns.toml)")
    s.set_defaults(func=_scan)
    c = sub.add_parser("clidoc", help="render docs/CLI.md from the parser")
    c.add_argument("--write", action="store_true", help="write docs/CLI.md")
    c.set_defaults(func=_clidoc)
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
