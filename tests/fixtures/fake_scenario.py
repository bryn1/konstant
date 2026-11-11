"""The scenario-writer part of the fake harness (tests/fixtures/fake_harness.py): the drafts it
writes into its KONSTANT-DRAFTS dir, after one `scenario-sees: ...` line per thing it tried to
read (var/runs, job clones, the board DB, the tokens, the store).

Scenario-writer reliability modes (wave L5-7; the drafts the L5-6b live model wrote, rebuilt):
  scenario-live           every attempt writes LIVE_DRAFTS (not held out, hint leaks, a hint over
                          200 characters, an EXPECT_RE matching empty output, both expectations,
                          too few): the lint must refuse every one, every time
  scenario-retry          attempt 1 writes LIVE_DRAFTS; once its prompt carries the refusal it
                          prints one `scenario-feedback: <line>` per reason line it was given and
                          writes the good set
  scenario-lint           follows the prompt's examples and its pre-check: writes a draft with a
                          leaking hint, runs KONSTANT-LINT (`scenario-lint: rc=N` + its output),
                          fixes the hint, writes a skeleton with `holdout new` and fills it, runs
                          the pre-check again; sealed on its first attempt
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCENARIOS = ("SCENARIO: greet uses the caller's name\nKIND: proof\n"
             "RUN: python3 -c \"from greeter import greet; print(greet('Ada'))\"\n"
             "EXPECT_EXIT: 0\nEXPECT_OUT: hello Ada\n"
             "HINT: names other than the default are used verbatim\n",
             "SCENARIO: the default greeting still works\nKIND: regression\n"
             "RUN: python3 -c \"from greeter import greet; print(greet().upper())\"\n"
             "EXPECT_EXIT: 0\nEXPECT_OUT: HELLO WORLD\n"
             "HINT: calling it without an argument keeps working\n")
# the L5-6b live drafts' refusal reasons, rebuilt for the fake planner's B1 brief (each breaks
# one rule; the lint refused exactly these shapes live: NOT HELD OUT, HINT LEAKS, HINT > 200,
# TRIVIAL EXPECT_RE, MALFORMED both/neither, TOO FEW)
LIVE_DRAFTS = (
    "SCENARIO: greet with the world\nKIND: proof\n"
    "RUN: python3 -c \"from greeter import greet; print(greet('world'))\"\n"
    "EXPECT_EXIT: 0\nEXPECT_OUT: hello world\nHINT: the greeting for a given name is wrong\n",
    "SCENARIO: greet Zoe\nKIND: proof\n"
    "RUN: python3 -c \"from greeter import greet; print(greet('Zoe'))\"\n"
    "EXPECT_EXIT: 0\nEXPECT_OUT: hello Zoe\nHINT: greet('Zoe') should print hello Zoe\n",
    "SCENARIO: a long hint\nKIND: proof\n"
    "RUN: python3 -c \"from greeter import greet; print(greet('Kim'))\"\n"
    "EXPECT_EXIT: 0\nEXPECT_OUT: hello Kim\nHINT: " + "names given are used " * 12 + "\n",
    "SCENARIO: any greeting\nKIND: proof\n"
    "RUN: python3 -c \"from greeter import greet; print(greet('Lu'))\"\n"
    "EXPECT_EXIT: 0\nEXPECT_RE: .*\nHINT: the result is not as documented\n",
    "SCENARIO: both expectations\nKIND: regression\n"
    "RUN: python3 -c \"from greeter import greet; print(greet())\"\n"
    "EXPECT_EXIT: 0\nEXPECT_OUT: hello world\nEXPECT_RE: hello.*\n"
    "HINT: the default stays as it was\n",
)
VACUOUS = ("SCENARIO: the module documents itself\nKIND: proof\n"
           "RUN: python3 -c \"import greeter; print(greeter.__doc__)\"\n"
           "EXPECT_EXIT: 0\nEXPECT_OUT: greeter: small greetings.\n"
           "HINT: the module keeps its docstring\n")


def scenario_writer(h: dict, MODE: str, PROMPT: str) -> None:
    ws = Path(os.environ.get("KONSTANT_HOME") or ".")
    tries = [("var/runs", ws / "var" / "runs"), ("board db", ws / "var" / "board.db"),
             ("secrets", ws / "var" / "secrets"), ("store", ws / "var" / "holdout")]
    proj = ws / "projects"
    tries += [(f"clone {p.name}", p) for p in sorted(proj.iterdir()) if "@" in p.name] \
        if proj.is_dir() else []
    for what, path in tries:
        try:
            seen = (sorted(x.name for x in path.iterdir()) if path.is_dir()
                    else [f"{len(path.read_bytes())} bytes"])
        except OSError as exc:
            seen = [f"denied ({type(exc).__name__})"]
        print(f"scenario-sees: {what}: {seen[:8]}")
    drafts = Path(h["DRAFTS"])
    if MODE == "scenario-memory":
        scenario_memory()
    retry = "## Your previous drafts were refused" in PROMPT
    if MODE == "scenario-lint":
        return scenario_lint(h, drafts)
    if MODE == "scenario-retry" and retry:
        section = PROMPT.split("## Your previous drafts were refused", 1)[1]
        for ln in section.splitlines():
            if ln.lstrip().startswith("- ") or ln.startswith("### "):
                print("scenario-feedback: " + ln.strip())
    texts = (VACUOUS, SCENARIOS[1]) if MODE == "weak-scenario" else \
        LIVE_DRAFTS if MODE == "scenario-live" or (MODE == "scenario-retry" and not retry) \
        else SCENARIOS
    for i, t in enumerate(texts, 1):
        (drafts / f"draft{i}.scenario").write_text(t)


def scenario_lint(h: dict, drafts: Path) -> None:
    """Follow the prompt: draft, run the pre-check it names, fix what it says, check again."""
    import shlex
    cmd = shlex.split(h["LINT"])
    konstant = cmd[:cmd.index("holdout")]

    def check() -> None:
        r = subprocess.run(cmd, cwd=drafts, capture_output=True, text=True)
        print(f"scenario-lint: rc={r.returncode}")
        for ln in (r.stdout + r.stderr).splitlines():
            print(f"scenario-lint: {ln}")
    (drafts / "proof.scenario").write_text(SCENARIOS[0].replace(
        "HINT: names other than the default are used verbatim",
        "HINT: greet should use the name Ada"))                 # leaks greet + ada (R8)
    check()
    (drafts / "proof.scenario").write_text(SCENARIOS[0])        # the hint in other words
    r = subprocess.run(konstant + ["holdout", "new", "--kind", "regression", "--out",
                                   "regression.scenario"], cwd=drafts, capture_output=True,
                       text=True)
    print(f"scenario-lint: new rc={r.returncode}")
    sk = (drafts / "regression.scenario").read_text()
    fill = dict(ln.split(": ", 1) for ln in SCENARIOS[1].splitlines())
    out = []
    for ln in sk.splitlines():
        key = ln.split(":", 1)[0]
        out.append(f"{key}: {fill[key]}" if "<FILL:" in ln and not ln.startswith("#") else ln)
    (drafts / "regression.scenario").write_text("\n".join(out) + "\n")
    check()


def scenario_memory() -> None:
    import json
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "kb_recall", "arguments": {"query": "greeting"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "kb_note", "arguments": {
                 "title": "scenario lesson", "text": "proof inputs must differ from the DoD's"}}}]
    r = subprocess.run([sys.executable, "-m", "konstant", "mcp", "memory"], capture_output=True,
                       text=True, input="".join(json.dumps(m) + "\n" for m in msgs))
    replies = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
    for rep in replies[1:]:
        text = rep.get("result", {}).get("content", [{}])[0].get("text", str(rep))
        print("scenario-memory: " + " | ".join(text.splitlines()[:3]))
    if not replies:
        print(f"scenario-memory: no server ({r.returncode}): {r.stderr.strip()[-200:]}")
