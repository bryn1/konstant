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
     phase's tool calls); with STUB_DSH_THEN=endpoint, runs a model loop against the provider
     the --patch file names (`baseURL`, the model in KONSTANT_MODEL): `POST
     <baseURL>/chat/completions` with stdin as the user message and one `bash` tool, streamed
     (server-sent events, as dsh's openai-completions provider asks), each tool call run as a
     command and its output sent back, until a reply has no tool call (the live pre-flight's
     scripted endpoint, konstant/harnesses/scripted.py, drives it in CI); else prints
     `dsh started`.

What a model's command sees is what dsh 0.2.2's bash tool gives it (wave L5-L, measured by
`konstant doctor --live-preflight` from inside a real phase): the harness's environment MINUS
every name matching /KEY|PASSWORD|SECRET|TOKEN/i and every DSH_* name (dsh-subprocess
SENSITIVE_ENV_PATTERN, scrubbedParentEnv), plus NO_COLOR=1, TERM=dumb, PAGER=cat, GIT_PAGER=cat
(bash-local ENV_OVERRIDES) and dsh's own DSH_HOME, DSH_SHELL=1, DSH_SESSION_ID, DSH_PROFILE,
DSH_PROFILE_DIR (shell-env); stdin is /dev/null, cwd the session's (the process cwd). The
STUB_DSH_THEN=fake modes and every `run:` action run in exactly that environment (tool_env), so
a variable konstant sets for a phase that dsh would drop is dropped here too (the L5-F2b live
finding: a GIT_CONFIG_KEY_0 lost on the way, every git call in the phase broken, CI green).
Not mirrored, on purpose: dsh's sandbox gives every command a fresh, empty /tmp, which would hide
the test workspaces (they live under /tmp, where a real dsh cannot work at all: doctor WARNs);
the pre-flight reports it live (`tmp-persists`).
Only the standard library; it never contacts a network or a model, except the 127.0.0.1
endpoint of STUB_DSH_THEN=endpoint.
"""
from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIPPED = ["@deepseek-ai/dsh-base"]
SENSITIVE = re.compile(r"KEY|PASSWORD|SECRET|TOKEN", re.I)        # dsh-subprocess
OVERRIDES = {"NO_COLOR": "1", "TERM": "dumb", "PAGER": "cat", "GIT_PAGER": "cat"}  # bash-local
SESSION = "session-" + str(uuid.uuid4())


def tool_env(profile: str = "headless") -> dict:
    """The environment of a command the model runs through dsh's bash tool (see the docstring)."""
    env = {k: v for k, v in os.environ.items()
           if not SENSITIVE.search(k) and not k.upper().startswith("DSH_")}
    env.update(OVERRIDES)
    env.update({"DSH_HOME": str(home()), "DSH_SHELL": "1", "DSH_SESSION_ID": SESSION,
                "DSH_PROFILE": profile, "DSH_PROFILE_DIR": str(home() / "profiles" / profile)})
    return env


def shell(command: str, profile: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=120,
                          env=tool_env(profile), cwd=os.getcwd(), stdin=subprocess.DEVNULL)


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
    """Creates the profile on first open, as dsh does; a home it cannot write (a forced home
    outside the jail's writable dirs: konstant runs the composition check jailed since L5-F2a)
    is read as it is."""
    d = home() / "profiles" / profile
    try:
        d.mkdir(parents=True, exist_ok=True)
        if not (d / "package.json").exists():
            (d / "package.json").write_text(json.dumps({"dsh": {"profile": {
                "bundles": SHIPPED + [f"@deepseek-ai/dsh-{profile}"]}}}))
        if not (d / "cordis.patch.yml").exists():
            (d / "cordis.patch.yml").write_text("# your patch layer\n[]\n")
    except OSError:
        pass
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
    pj = d / "package.json"
    bundles = json.loads(pj.read_text())["dsh"]["profile"]["bundles"] if pj.is_file() else \
        SHIPPED + [f"@deepseek-ai/dsh-{profile}"]
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
    """Appends to $STUB_DSH_LOG; skipped where it is not writable (the jailed composition check
    writes only its own dsh home)."""
    if os.environ.get("STUB_DSH_LOG"):
        try:
            with open(os.environ["STUB_DSH_LOG"], "a") as fh:
                fh.write(json.dumps(rec) + "\n")
        except OSError:
            pass


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
         "loaded": loaded, "env_names": sorted(os.environ),     # what konstant gave dsh
         "tool_env_names": sorted(tool_env(profile))})          # what a model's command gets
    for act in filter(None, os.environ.get("STUB_DSH_ACTIONS", "").split(";")):
        verb, _, target = act.partition(":")
        target = os.path.expandvars(target)
        try:
            if verb == "sleep":
                time.sleep(float(target))
                continue
            if verb == "run":
                r = shell(target, profile)
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
        env = tool_env(profile)                  # the fake's actions are the model's commands
        os.environ.clear()
        os.environ.update(env)
        sys.argv = [str(HERE / "fake_harness.py")]
        runpy.run_path(str(HERE / "fake_harness.py"), run_name="__main__")
        return 0
    if os.environ.get("STUB_DSH_THEN") == "endpoint":
        return model_loop(profile, patches)
    if "-" in rest:
        sys.stdin.read()
    print("dsh started")
    return 0


def _provider(patches: list) -> str:
    for f in patches:
        try:
            m = re.search(r'^\s*baseURL:\s*"([^"]+)"', Path(f).read_text(), re.M)
        except OSError:
            continue
        if m:
            return m.group(1).rstrip("/")
    raise SystemExit("dsh: no provider baseURL in the --patch files")


def _complete(url: str, body: dict) -> dict:
    """One streamed chat completion, folded into {"content", "tool_calls"}."""
    import urllib.request
    req = urllib.request.Request(url + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    content, calls = "", {}
    with urllib.request.urlopen(req, timeout=60) as r:
        for raw in r.read().decode().splitlines():
            if not raw.startswith("data: ") or raw == "data: [DONE]":
                continue
            for ch in json.loads(raw[6:]).get("choices") or []:
                d = ch.get("delta") or {}
                content += d.get("content") or ""
                for tc in d.get("tool_calls") or []:
                    c = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                    c["id"] = tc.get("id") or c["id"]
                    c["name"] = (tc.get("function") or {}).get("name") or c["name"]
                    c["args"] += (tc.get("function") or {}).get("arguments") or ""
    return {"content": content, "tool_calls": [calls[k] for k in sorted(calls)]}


def model_loop(profile: str, patches: list) -> int:
    url, model = _provider(patches), os.environ.get("KONSTANT_MODEL", "default")
    tools = [{"type": "function", "function": {"name": "bash", "parameters": {
        "type": "object", "properties": {"command": {"type": "string"},
                                         "description": {"type": "string"}}}}}]
    msgs = [{"role": "user", "content": sys.stdin.read()}]
    for _ in range(20):
        r = _complete(url, {"model": model, "stream": True, "messages": msgs, "tools": tools})
        if not r["tool_calls"]:
            print(r["content"])
            return 0
        msgs.append({"role": "assistant", "content": r["content"] or None, "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"],
                                                             "arguments": c["args"]}}
            for c in r["tool_calls"]]})
        for c in r["tool_calls"]:
            cmd = json.loads(c["args"] or "{}").get("command", "")
            p = shell(cmd, profile)
            log({"act": "tool:bash", "rc": p.returncode})
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": p.stdout + p.stderr + f"\n[exit code: {p.returncode}]"})
    return 1


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
