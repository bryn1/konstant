"""What makes a scenario writer's drafts easy to get right (docs/LEVEL5.md 3.4, wave L5-7), without
moving the bar: the rules in short checkable form, worked examples, a skeleton, and a pre-check
the writer runs on its own drafts inside its phase. Every verdict here comes from holdout/lint.py
(the same `parse`, `lint` and `lint_set` that `seal()` runs); this module only explains.

- `RULES` / `EXAMPLES`: carried in the scenario writer's prompt (holdout/author.py). The examples
  are for a generic CLI project (`tempconv`), never the job's own, and each passes the lint.
- `skeleton(kind)`: `konstant holdout new` - every value the model must write is a `<FILL: ...>`
  placeholder, which the lint refuses until it is filled.
- the context file `.konstant-draft.json` in the drafts dir: the job's brief and DoD and the set
  size, written by konstant before the phase, so `konstant holdout lint --draft` can apply the
  held-out rule. It is the job the writer already sees in its prompt; editing it only weakens the
  writer's own pre-check - `seal()` lints again from the board's copy.
- `check(paths, ctx)`: the pre-check. No board, no store: it reads only the files it is given and
  refuses one that lies in a sealed store outside a scenario writer's `drafts/` dir. It does not
  run the negative control (that needs konstant's jail); the writer may run its RUN on the target
  itself.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from konstant.holdout import lint

CONTEXT = ".konstant-draft.json"

RULES = """\
R1  One scenario per file `<name>.scenario`; only `KEY: value` lines (a line that starts with `#`
    is a comment). Keys, each once: SCENARIO, KIND, RUN, EXPECT_EXIT, EXPECT_OUT or EXPECT_RE,
    HINT. CANARY is added for you. No other key.
R2  KIND is `proof` (new behaviour: it must FAIL on the target as it is now) or `regression`
    (behaviour that exists: it must PASS now and after the work).
R3  Exactly ONE of EXPECT_OUT (the whole stdout, stripped, compared for equality) and EXPECT_RE
    (a Python regex that must match the WHOLE stripped stdout). Only stdout and the exit code are
    checked, never stderr.
R4  EXPECT_EXIT is the expected exit code, 0-255.
R5  RUN is ONE command, split into words like a shell would, run WITHOUT a shell in the project
    directory: no ; & | < > $ or backtick outside quotes (quote a `python3 -c` program). Its
    program must exist on the target NOW (python3, or a file already in the repository): a
    command the job adds does not exist yet, so reach new code as `python3 -m <module>`,
    `python3 <file>` or `python3 -c "..."`. Never a test runner (pytest, unittest, npm test, make
    test, ...).
R6  Not trivial: EXPECT_OUT is not empty; EXPECT_RE is searched in five test strings (empty, a
    space, `x`, one line holding every letter, digit and punctuation sign, and an error line
    `probe-canary: no such file or directory`) and must be found in NONE of them. So no `.*`,
    `.+`, `\\S+`, `[0-9.]+` or an empty alternative: put literal text of the real answer in it.
R7  Held out: the expectation (EXPECT_OUT as a whole; for EXPECT_RE every stretch of 4 or more
    plain characters between regex symbols) and every quoted RUN argument of 4 or more characters
    must NOT appear anywhere in the job's brief or DoD. Use other names, numbers and words than
    the brief's own examples. Prefer EXPECT_OUT with an input of your own.
R8  HINT is at most 200 characters and shares NO word (3 or more letters or digits, compared
    case-insensitively; small words like the, and, with, for are free) with RUN or with the
    expectation. Say what behaviour failed in other words: it is the only text a failure shows.
R9  The set: at least {need} scenarios, at least one `proof`.
R10 Before sealing, konstant runs each scenario on the target as it is now: a proof that already
    passes (VACUOUS), a regression that fails (REGRESSION FAILS) or a command that cannot start
    (UNRUNNABLE) is refused."""

EXAMPLES = (
    ("proof through the command line (the brief of that project showed 32 -> 0.0, so 212 is new)",
     "SCENARIO: converting a boiling point from Fahrenheit gives Celsius\n"
     "KIND: proof\n"
     "RUN: python3 -m tempconv --to-celsius 212\n"
     "EXPECT_EXIT: 0\n"
     "EXPECT_OUT: 100.0\n"
     "HINT: a conversion to the metric scale prints the wrong number\n"),
    ("regression through the library (it works on the target now and must keep working)",
     "SCENARIO: an existing conversion keeps its result\n"
     "KIND: regression\n"
     "RUN: python3 -c \"import tempconv; print(tempconv.to_fahrenheit(-40))\"\n"
     "EXPECT_EXIT: 0\n"
     "EXPECT_OUT: -40.0\n"
     "HINT: a conversion that worked before the change now gives another value\n"),
    ("proof with a regex, only when the output may vary: its literal `v` and dots keep it from "
     "matching any output (R6), and it holds no stretch of 4+ plain characters, so nothing of it "
     "can be in the brief (R7; the program's own name would be)",
     "SCENARIO: the program reports its release as three dotted numbers\n"
     "KIND: proof\n"
     "RUN: python3 -m tempconv --version\n"
     "EXPECT_EXIT: 0\n"
     "EXPECT_RE: v[0-9]+\\.[0-9]+\\.[0-9]+\n"
     "HINT: asking which release is installed gives no proper answer\n"),
)


def examples_text() -> str:
    out = []
    for i, (why, text) in enumerate(EXAMPLES, 1):
        out += [f"Example {i}: {why}", "```", text.rstrip("\n"), "```"]
    return "\n".join(out)


def skeleton(kind: str, regex: bool = False) -> str:
    """A scenario file with the format right and every judgement left to the writer."""
    if kind not in lint.KINDS:
        raise ValueError(f"--kind must be one of {', '.join(lint.KINDS)}")
    must = ("FAIL on the target as it is now and pass once the job is done" if kind == "proof"
            else "PASS on the target now and after the work")
    expect = ("EXPECT_RE: <FILL: a regex over the WHOLE stdout, with literal text of the answer>"
              if regex else "EXPECT_OUT: <FILL: the whole expected stdout>")
    return (f"# written by `konstant holdout new --kind {kind}`: replace every <FILL: ...> value,\n"
            f"# then run `konstant holdout lint --draft .`. A {kind} must {must}.\n"
            "SCENARIO: <FILL: one line naming the behaviour this checks>\n"
            f"KIND: {kind}\n"
            "RUN: <FILL: one command, no shell; its program exists on the target now>\n"
            "EXPECT_EXIT: 0\n"
            f"{expect}\n"
            "HINT: <FILL: what failed, in words that are not in RUN or the expectation>\n")


def write_context(drafts: Path, job: dict, need: int) -> Path:
    p = Path(drafts) / CONTEXT
    p.write_text(json.dumps({"job": job.get("display_id") or str(job.get("id")),
                             "brief": job.get("brief") or "",
                             "acceptance": job.get("acceptance") or "", "need": need}))
    os.chmod(p, 0o600)
    return p


def read_context(path: Path | None) -> dict | None:
    if path is None or not Path(path).is_file():
        return None
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


class DraftRefused(Exception):
    """A path the pre-check will not read (exit 2)."""


def sealed_roots(home: Path) -> list:
    from konstant import machinery
    return [os.path.realpath(Path(home) / d) for d in machinery.SEALED] + \
        [os.path.realpath(p) for p in machinery.external_store(Path(home))]


def allowed(path: str, roots: list) -> bool:
    """A file inside a sealed store is read only as a scenario writer's draft:
    <store>/<job>/drafts/<name>.scenario. Anything else there (a sealed H<n>.scenario, the memory
    vault, the research store) is refused, so the pre-check is never a reader of the store."""
    real = os.path.realpath(path)
    for r in roots:
        if real == r or real.startswith(r + os.sep):
            rel = Path(real).relative_to(r).parts
            return len(rel) == 3 and rel[0].isdigit() and rel[1] == "drafts"
    return True


def expand(paths: list, home: Path) -> list:
    """FILE or DIR arguments -> the draft files (a dir: every `*.scenario` in it, sorted)."""
    roots, out = sealed_roots(home), []
    for p in map(Path, paths):
        files = sorted(x for x in p.glob("*.scenario") if x.is_file()) if p.is_dir() else [p]
        for f in files:
            if not allowed(str(f), roots):
                raise DraftRefused(f"{f} lies in a sealed store and is not a scenario writer's "
                                   "draft: `holdout lint` reads drafts only")
            if f.is_symlink():
                raise DraftRefused(f"{f} is a symlink: a draft is a plain file")
            out.append(f)
    return out


def check(files: list, ctx: dict | None) -> dict:
    """The pre-check over `files` as one set -> {"drafts": [{file, kind, reasons}], "set":
    [reasons], "ok": bool, "held_out_checked": bool}. Verdicts are holdout/lint.py's, with
    detail (each draft is named by its file, as the writer named it)."""
    brief = (ctx or {}).get("brief") or ""
    acceptance = (ctx or {}).get("acceptance") or ""
    need = int((ctx or {}).get("need") or 0)
    rows, parsed = [], []
    for f in files:
        name = Path(f).name
        try:
            sc = lint.parse(lint.with_canary(Path(f).read_bytes()), name, detail=True)
        except OSError as exc:
            rows.append({"file": name, "kind": None, "reasons": [f"UNREADABLE: {name} "
                                                                 f"({exc.strerror})"]})
            continue
        except lint.ScenarioError as exc:
            rows.append({"file": name, "kind": None, "reasons": [str(exc)]})
            continue
        parsed.append(sc)
        rows.append({"file": name, "kind": sc.kind,
                     "reasons": lint.lint(sc, brief, acceptance, detail=True)})
    sets = lint.lint_set(parsed, max(need, 1), str(ctx.get("job") or "?")) if ctx else \
        [r for r in lint.lint_set(parsed, 1, "?") if r.startswith("DUPLICATE CANARY")]
    if not files:
        sets = [f"TOO FEW: no `*.scenario` draft given (need {need or 'at least 1'})"]
    ok = not sets and all(not r["reasons"] for r in rows)
    return {"drafts": rows, "set": sets, "ok": ok, "held_out_checked": ctx is not None}


def report(res: dict) -> str:
    lines = []
    for r in res["drafts"]:
        if r["reasons"]:
            lines.append(f"{r['file']}: REFUSED")
            lines += [f"  - {x}" for x in r["reasons"]]
        else:
            lines.append(f"{r['file']}: ok ({r['kind']})")
    if res["set"]:
        lines.append("the set: REFUSED")
        lines += [f"  - {x}" for x in res["set"]]
    if not res["held_out_checked"]:
        lines.append(f"note: no {CONTEXT} next to the drafts (nor --context): the held-out rule "
                     "R7 and the set size R9 were not checked")
    proofs = sum(1 for r in res["drafts"] if r["kind"] == "proof" and not r["reasons"])
    lines.append(f"DRAFTS OK: {len(res['drafts'])} draft(s), {proofs} proof(s). konstant still "
                 "runs each on the target before sealing (R10)" if res["ok"] else
                 "DRAFTS REFUSED: fix every reason above, then run this check again")
    return "\n".join(lines)


_HID = re.compile(r"\bH([1-9][0-9]*)\b")


def feedback(reasons: list, hids: dict, attempt: int, attempts: int, ctx: dict) -> str:
    """The retry prompt's section: for each draft its file name, the seal's exact reasons for it,
    the same rules in detail (what tripped each) and the draft as it was written; then the
    reasons about the set. Only this job's drafts (`hids`: H<n> -> its draft path; the seal
    names nothing else), and only in the scenario writer's own prompt, inside the sealed store."""
    per: dict = {h: [] for h in hids}
    rest = []
    for r in reasons:
        hit = [h for h in (f"H{m}" for m in _HID.findall(r)) if h in per]
        if hit:
            per[hit[0]].append(r)
        else:
            rest.append(r)
    out = [f"Attempt {attempt} of {attempts} was refused. Your drafts dir is empty again: write "
           "the whole set anew, fixing every reason below (each draft was checked as the H<n> "
           "named beside it), and run the pre-check before you finish."]
    for hid, path in hids.items():
        p = Path(path)
        try:
            text = p.read_text(errors="replace")
        except OSError:
            text = ""
        out += ["", f"### {p.name} (checked as {hid}): "
                + ("REFUSED" if per[hid] else "no reason of its own")]
        out += [f"- {r}" for r in per[hid]]
        if per[hid] and text:
            detail = check([p], ctx)["drafts"][0]["reasons"]
            if detail:
                out += ["  the same rules in detail (what tripped them):"]
                out += [f"  - {d}" for d in detail]
        if text:
            out += ["  as you wrote it:", "```", text.rstrip("\n")[:3000], "```"]
    if rest:
        out += ["", "### the set"] + [f"- {r}" for r in rest]
    return "\n".join(out)
