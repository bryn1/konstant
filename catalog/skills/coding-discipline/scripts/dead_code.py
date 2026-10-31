#!/usr/bin/env python3
"""dead_code.py - deterministic dead-code finder (skill coding-discipline, "Dead code"). Stdlib only.

Usage: dead_code.py ROOT --live PATH [--live PATH ...] [--lib DIR ...] [--driver-text FILE ...] [--allow FILE] [--no-fns]
  ROOT          repo root (searched for drivers of bins/scripts).
  --live        the code that RUNS in production (a service's src dir, an app package, an entry file). bin/ dirs and
                tests under it are not live.
  --lib         library dirs whose modules are only live when the live set reaches them (transitively).
  --driver-text extra text that can drive a bin/script (e.g. a crontab dump, unit files).
  --allow       lines `KIND path-or-name  reason` that are kept on purpose (printed as ALLOWED, not counted).
Findings (one per line; exit 1 when any is not allowed, else 0):
  ORPHAN-MODULE  a --lib module (Rust .rs / Python .py / C# .cs / TypeScript .ts .tsx / .mjs) no live code reaches.
  UNCALLED-FN    a `pub fn` (Rust) / top-level `def` (Python) / `public` method (C#) / exported name (TS, mjs) in
                 reached code whose name occurs in no other reached, non-test line.
  DRIVERLESS     a Rust bin (src/bin/*.rs) or a shell script that nothing invokes: its name occurs in no other
                 non-doc file of ROOT nor in --driver-text.
Name-based and conservative: a name collision can hide a finding (false negative); a reported finding has zero
textual callers. Calls by string, reflection, macros, FFI or another language are NOT seen: add them to --allow with
the reason. C#: a .cs named by a <Compile Include="..."> in a .csproj counts as reached; generated .g.cs/.designer.cs
files and obj/ dirs are skipped. TypeScript: an import resolves by module name (a dir's index.* under the dir name);
.d.ts and *.test.ts/*.spec.ts files are not scanned code.
"""
import argparse, os, re, sys

SKIP_DIRS = {".git", "target", "node_modules", "__pycache__", ".audits", ".tmp", "venv", ".venv", "obj"}
DOC_EXT = (".md", ".txt", ".rst")
GEN_CS = (".g.cs", ".g.i.cs", ".designer.cs")   # generated C#, never hand-scanned


def walk(path, exts):
    if os.path.isfile(path):
        yield path
        return
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith(exts):
                yield os.path.join(root, f)


def is_test_path(p):
    parts = p.split(os.sep)   # "not scanned code": tests, benches, generated C#
    return (any(d in ("tests", "test", "benches") for d in parts[:-1]) or parts[-1].startswith("test_")
            or parts[-1].endswith(("_test.py", "_test.rs", "Test.cs", "Tests.cs")) or parts[-1].startswith("Test") and parts[-1].endswith(".cs")
            or p.lower().endswith(GEN_CS)
            or parts[-1].endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".d.ts")))


def is_bin(p):
    return f"{os.sep}bin{os.sep}" in p and p.endswith(".rs")


def code_lines(p, numbered=False):
    """Non-test, non-comment lines of a source file. Rust: each `#[cfg(test)]` item (a `mod tests { ... }` block or one
    item) is skipped by brace depth, so a test module in the MIDDLE of a file does not hide the code after it."""
    try:
        with open(p, errors="ignore") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    out, skip, depth, opened = [], False, 0, False
    for n, ln in enumerate(lines, 1):
        s = ln.strip()
        if p.endswith(".rs") and s.startswith("#[cfg(test)]"):
            skip, depth, opened = True, 0, False
            continue
        if skip:
            depth += ln.count("{") - ln.count("}")
            opened = opened or "{" in ln
            if (opened and depth <= 0) or (not opened and s.endswith(";")):
                skip = False
            continue
        if s.startswith(("//", "#")) and not s.startswith(("#[", "#!")):
            continue
        out.append((n, ln) if numbered else ln)
    return out


def mod_name(p):
    b = os.path.splitext(os.path.basename(p))[0]
    if b == "index":   # TS/ESM: a dir import resolves to its index — the dir names the module
        return os.path.basename(os.path.dirname(p))
    return b


def refs_module(text, m, ext):
    if ext == ".py":
        return bool(re.search(rf"\b(?:import|from)\s+[\w.]*\b{m}\b|from\s+[\w.]+\s+import\s+[^\n]*\b{m}\b|\b{m}\.\w", text))
    if ext == ".cs":   # C# has no file imports: a namespace `using`, a static/member access, an instantiation or a base class
        return bool(re.search(rf"\busing\s[\w.:* ]*\b{m}\b|(?<!\w){m}\.\w|\bnew\s+{m}\b|:\s*{m}\b", text))
    if ext in (".ts", ".tsx"):   # ESM: a named module in a from / import() / bare-import clause
        return bool(re.search(rf"""(?:from\s+|import\s*|import\s*\()\s*['"][^'"]*/{re.escape(m)}(?:\.(?:js|jsx|mjs))?['"]|(?:from\s+|import\s*|import\s*\()\s*['"]{re.escape(m)}(?:\.(?:js|jsx|mjs))?['"]""", text))
    return bool(re.search(rf"(?<!\w){m}::|::{m}\b|\buse\s[^;]*\b{m}\b[^;]*;", text))


def defs(p, lines):
    if p.endswith(".rs"):
        rx, ng = re.compile(r"^\s*pub(?:\([^)]*\))?\s+(?:const\s+|async\s+|unsafe\s+)*fn\s+(\w+)"), 1
    elif p.endswith(".cs"):   # C#: a public/internal method; the >=1 type tokens before the name drop ctors (no return type)
        rx, ng = re.compile(r"^\s*(?:public|internal)\s+((?:(?:static|virtual|async|sealed|unsafe|partial|extern|override|new|readonly)\s+)*[\w<>\[\],\.\?]+\s+)+(\w+)\s*\("), 2
    elif p.endswith((".ts", ".tsx")):   # TS/TSX: EXPORTED names only — a non-exported const is module-local
        rx, ng = re.compile(r"^\s*export\s+(?:async\s+)?(?:function|const|let|var|class)\s+(\w+)"), 1
        out = []
        brace = re.compile(r"^\s*export\s*\{([^}]*)\}")
        for i, ln in enumerate(lines):
            m = rx.match(ln)
            if m and m.group(1) not in ("main",):
                out.append((m.group(1), i + 1))
                continue
            b = brace.match(ln)   # `export { a, b as c }` — the ORIGINAL names are the defs
            if b:
                for part in b.group(1).split(","):
                    tok = part.strip().split(" as ")[0].strip()
                    if tok and tok != "default" and re.fullmatch(r"\w+", tok):
                        out.append((tok, i + 1))
        return out
    elif p.endswith(".mjs"):   # .mjs libs: same export-const/function surface
        rx = re.compile(r"^\s*export\s+(?:async\s+)?(?:function|const|let|var|class)\s+(\w+)")
        return [(m.group(1), i + 1) for i, ln in enumerate(lines) for m in [rx.match(ln)] if m]
    else:
        rx, ng = re.compile(r"^def\s+(\w+)\s*\("), 1
    out = []
    for i, ln in enumerate(lines):
        m = rx.match(ln)
        if not m or m.group(ng) in ("main", "new", "default", "Main") or m.group(ng).startswith("__"):
            continue
        if ng == 2 and "override" in m.group(1):
            continue   # dispatched by the runtime, not called by name — same rationale as the decorated defs below
        prev = lines[i - 1].strip() if i else ""
        if prev.startswith(("@", "[", "#[no_mangle]", "#[tokio", "#[export")):
            continue   # decorated / exported: called by a framework, not by name
        out.append((m.group(ng), i + 1))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root"); ap.add_argument("--live", action="append", required=True)
    ap.add_argument("--lib", action="append", default=[]); ap.add_argument("--driver-text", action="append", default=[])
    ap.add_argument("--allow"); ap.add_argument("--no-fns", action="store_true")
    a = ap.parse_args(argv)
    exts = (".rs", ".py", ".cs", ".ts", ".tsx", ".mjs")
    live = [p for d in a.live for p in walk(d, exts) if not is_test_path(p) and not is_bin(p)]
    libmods = {p: mod_name(p) for d in a.lib for p in walk(d, exts)
               if not is_test_path(p) and not is_bin(p) and mod_name(p) not in ("lib", "mod", "main", "__init__", "__main__")}
    text = {p: "\n".join(code_lines(p)) for p in set(live) | set(libmods)}
    # cheap .csproj parse (data, not source): a .cs compiled by a project IS wired
    compiled = {os.path.basename(m.group(1).replace("\\", "/")) for p in walk(a.root, (".csproj",))
                for m in re.finditer(r'<Compile\s+Include="([^"]+)"', open(p, errors="ignore").read())}
    reached, frontier = set(live) | {p for p in libmods if p.endswith(".cs") and os.path.basename(p) in compiled}, list(live)
    while frontier:   # transitive closure over module references
        src = frontier.pop()
        for p, m in libmods.items():
            if p not in reached and refs_module(text[src], m, os.path.splitext(p)[1]):
                reached.add(p); frontier.append(p)
    findings = [("ORPHAN-MODULE", os.path.relpath(p, a.root), "no live code reaches it") for p in sorted(libmods) if p not in reached]
    if not a.no_fns:
        corpus = {p: code_lines(p) for p in reached}
        for p in sorted(reached):
            for name, ln in defs(p, corpus[p]):
                rx = re.compile(rf"\b{name}\b")
                hits = sum(len(rx.findall(l)) for q, ls in corpus.items() for l in ls)
                if hits <= 1:   # only its own definition
                    findings.append(("UNCALLED-FN", f"{os.path.relpath(p, a.root)}:{ln}", name))
    drivers = "\n".join(open(f, errors="ignore").read() for f in a.driver_text if os.path.isfile(f))
    allfiles = [p for p in walk(a.root, ("",)) if not p.endswith(DOC_EXT) and os.path.basename(p) not in ("Cargo.toml", "Cargo.lock")]
    runnable = [p for p in allfiles if (is_bin(p) and not is_test_path(p)) or (p.endswith(".sh") and not is_test_path(p))]
    for p in sorted(runnable):
        stem = mod_name(p) if p.endswith(".rs") else os.path.basename(p)
        rx = re.compile(rf"(?<![\w-]){re.escape(stem)}(?![\w-])")
        used = rx.search(drivers) or any(q != p and rx.search(open(q, errors="ignore").read()) for q in allfiles if os.path.getsize(q) < 2_000_000)
        if not used:
            findings.append(("DRIVERLESS", os.path.relpath(p, a.root), "nothing invokes it"))
    allowed = set()
    if a.allow and os.path.isfile(a.allow):
        allowed = {tuple(l.split()[:2]) for l in open(a.allow) if l.strip() and not l.startswith("#")}
    bad = 0
    for kind, where, what in findings:
        ok = (kind, where) in allowed or (kind, what) in allowed
        bad += not ok
        print(f"{'ALLOWED ' if ok else ''}{kind:13} {where}  {what}")
    print(f"dead_code: {len(set(libmods) & reached)}/{len(libmods)} lib modules reached from {len(live)} live files, {bad} finding(s) not allowed", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
