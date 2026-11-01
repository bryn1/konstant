#!/usr/bin/env python3
"""A stand-in for the `dsh` CLI with no model (second security review): the surface konstant uses, faithful to
dsh 0.2.1's own rules (apps/cli/src/dump-config.ts, packages/boot/app-boot/src/profile.ts):

`dsh --profile P [--patch F]... --dump-config`
  opens profile P under $DSH_HOME (creating profiles/P/{package.json,cordis.patch.yml} on first
  open, as dsh does) and prints the composition's layer headers: one per shipped bundle
  (`# == @deepseek-ai/dsh-base`, `..., patched by @deepseek-ai/dsh-<P>`), one per extra bundle in
  the profile's package.json, then for the profile's cordis.patch.yml, $DSH_HOME/cordis.patch.yml
  and each --patch file that holds entries: `# == ..., patched by <file>` per id-patch entry and
  `# == <file>` per insert entry. STUB_DSH_DUMP: `empty` prints nothing (exit 0, like dsh on
  Node 20), `fail` exits 3, `forced` ignores DSH_HOME and uses STUB_DSH_FORCED_HOME (a launcher
  that exports its own home).

`dsh --profile P [--patch F]... [ARGS]` (a run)
  1. "loads" the user layers the way dsh would run their plugins: every `# STUB-PAYLOAD: <python>`
     line in the profile's cordis.patch.yml under $DSH_HOME is executed (a planted plugin);
  2. runs the scripted actions of STUB_DSH_ACTIONS (`;`-separated, each `write:<path>`,
     `plant:<path>` = write an insert layer whose payload is STUB_DSH_PAYLOAD, `sleep:<s>`, or
     `run:<command>` = a shell command the session's model runs, logged with its exit code and
     output: the host-agents tests, [confinement] host_agents),
     recording each outcome as a JSON line in $STUB_DSH_LOG (when set) with the env it saw;
  3. with STUB_DSH_THEN=fake, hands stdin to tests/fixtures/fake_harness.py (its modes act as the
     phase's tool calls); else prints `dsh started`.
Only the standard library; it never contacts a network or a model.
"""
from __future__ import annotations

import json
import os
import re
import runpy
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIPPED = ["@deepseek-ai/dsh-base"]


def entries(path: Path) -> list:
    """('id'|'insert') per top-level entry of a patch file (comments and `[]` hold none)."""
    try:
        text = path.read_text()
    except OSError:
        return []
    out = []
    for ln in text.splitlines():
        if re.match(r"^- insert:", ln):
            out.append("insert")
        elif re.match(r"^- id:", ln):
            out.append("id")
    return out


def args():
    a = sys.argv[1:]
    profile, patches, rest = "headless", [], []
    i = 0
    while i < len(a):
        if a[i] == "--profile":
            profile, i = a[i + 1], i + 2
        elif a[i] == "--patch":
            patches.append(os.path.abspath(a[i + 1]))
            i += 2
        else:
            rest.append(a[i])
            i += 1
    return profile, patches, rest


def home() -> Path:
    if os.environ.get("STUB_DSH_DUMP") == "forced":
        return Path(os.environ["STUB_DSH_FORCED_HOME"])
    return Path(os.environ.get("DSH_HOME") or os.path.expanduser("~/.dsh"))


def open_profile(profile: str) -> Path:
    d = home() / "profiles" / profile
    d.mkdir(parents=True, exist_ok=True)
    if not (d / "package.json").exists():
        (d / "package.json").write_text(json.dumps({"dsh": {"profile": {
            "bundles": SHIPPED + [f"@deepseek-ai/dsh-{profile}"]}}}))
    if not (d / "cordis.patch.yml").exists():
        (d / "cordis.patch.yml").write_text("# your patch layer\n[]\n")
    return d


def dump(profile: str, patches: list) -> int:
    mode = os.environ.get("STUB_DSH_DUMP", "")
    log({"dump": sys.argv[1:], "DSH_HOME": os.environ.get("DSH_HOME")})
    if mode == "fail":
        print("dsh: boom", file=sys.stderr)
        return 3
    if mode == "empty":
        return 0
    for f in patches:
        if not Path(f).is_file():
            print(f"dsh: cannot read patch file {f}", file=sys.stderr)
            return 1
    d = open_profile(profile)
    bundles = json.loads((d / "package.json").read_text())["dsh"]["profile"]["bundles"]
    lines = ["# == @deepseek-ai/dsh-base", f"# == @deepseek-ai/dsh-base, patched by "
             f"@deepseek-ai/dsh-{profile}"]
    lines += [f"# == {b}" for b in bundles if b not in SHIPPED + [f"@deepseek-ai/dsh-{profile}"]]
    patchers = []                     # id-patches of one entry: `patched by A, B` (dsh's join)
    for f in [d / "cordis.patch.yml", home() / "cordis.patch.yml", *map(Path, patches)]:
        for kind in entries(f):
            if kind == "insert":
                lines.append(f"# == {f}")
            else:
                patchers.append(str(f))
    if patchers:
        lines.append(f"# == @deepseek-ai/dsh-base, patched by {', '.join(patchers)}")
    print("\n".join(lines) + "\n- id: stub\n")
    return 0


def log(rec: dict) -> None:
    if os.environ.get("STUB_DSH_LOG"):
        with open(os.environ["STUB_DSH_LOG"], "a") as fh:
            fh.write(json.dumps(rec) + "\n")


def run(profile: str, patches: list, rest: list) -> int:
    layer = home() / "profiles" / profile / "cordis.patch.yml"
    loaded = []
    for f in (layer, home() / "cordis.patch.yml"):
        try:
            text = f.read_text()
        except OSError:
            continue
        for ln in text.splitlines():
            m = re.match(r"^# STUB-PAYLOAD: (.*)$", ln)
            if m:
                loaded.append(str(f))
                exec(m.group(1), {"__name__": "payload"})       # the planted plugin runs
    open_profile(profile)
    log({"argv": sys.argv[1:], "DSH_HOME": os.environ.get("DSH_HOME"), "cwd": os.getcwd(),
         "loaded": loaded})
    for act in filter(None, os.environ.get("STUB_DSH_ACTIONS", "").split(";")):
        verb, _, target = act.partition(":")
        target = os.path.expandvars(target)
        try:
            if verb == "sleep":
                time.sleep(float(target))
                continue
            if verb == "run":
                import subprocess
                r = subprocess.run(target, shell=True, capture_output=True, text=True,
                                   timeout=60)
                log({"act": act, "rc": r.returncode, "out": r.stdout, "err": r.stderr})
                continue
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            body = "x\n" if verb == "write" else (
                "- insert:\n    - id: planted\n      name: file:///planted.mjs\n"
                f"# STUB-PAYLOAD: {os.environ.get('STUB_DSH_PAYLOAD', 'pass')}\n")
            with open(target, "a") as fh:
                fh.write(body)
            log({"act": act, "result": "WROTE"})
        except OSError as exc:
            log({"act": act, "result": type(exc).__name__})
    if os.environ.get("STUB_DSH_THEN") == "fake":
        sys.argv = [str(HERE / "fake_harness.py")]
        runpy.run_path(str(HERE / "fake_harness.py"), run_name="__main__")
        return 0
    if "-" in rest:
        sys.stdin.read()
    print("dsh started")
    return 0


def main() -> int:
    profile, patches, rest = args()
    if "--version" in rest:
        print("0.2.1-stub")
        return 0
    if "--dump-config" in rest:
        return dump(profile, patches)
    return run(profile, patches, rest)


if __name__ == "__main__":
    sys.exit(main())


def install(bindir) -> Path:
    """Put this stub on a PATH directory as `dsh`; returns its path."""
    p = Path(bindir) / "dsh"
    p.write_text(f'#!/bin/sh\nexec {sys.executable} {Path(__file__).resolve()} "$@"\n')
    p.chmod(0o755)
    return p
