"""The evidence contract on `close` (DESIGN §4.3).

1. Evidence: `verify_cmd` non-empty and not a no-op (`true`, `:`, `exit 0`, a bare
   `echo`/`printf`: it checks nothing; REVIEW F-02), `verify_exit` an integer equal to 0,
   `verify_output` non-empty. Every failing field is named at once.
2. Vacuity: output that says in its own words it measured NOTHING is refused, unless the same
   output reports a non-zero count of subjects somewhere else.
3. Negative control (opt-in): a supplied `control_cmd` must have exited non-zero and not 126/127.
4. Warnings only: no `DOCS:` line; every PROBE points only at the evidence file itself
   (self-attested).
Each of 1-3 has a mode (`off | warn | strict`) in [board.policy].

The vacuity lexicon turns on one distinction:
    zero SUBJECTS - "Ran 0 tests", "collected 0 items", "no files to check" -> REFUSED;
    zero DEFECTS  - "0 errors", "0 tests failed", "(0 rows)"             -> the clean answer.
Shapes that read both ways ("no matches", "no files matched", "nothing to commit") are absent on
purpose: each is the passing output of a real check that asserts an absence. A rule that refuses
honest evidence is worse than no rule. Both halves of the corpus live in tests/board.
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Optional

OUTPUT_CAP = 4000

_VACUOUS_PHRASES = (
    re.compile(r"(?i)\bran 0 tests\b"),
    re.compile(r"(?i)\bno tests (?:ran|were run|executed)\b"),
    re.compile(r"(?i)\bno tests (?:were )?found\b"),
    re.compile(r"(?i)\bcollected 0 items\b"),
    # The lookahead is the whole difference between "0 tests ran" (nothing measured) and
    # "0 tests failed" (everything measured, and passed). The (?<![:=]) lookbehind: a colon or
    # equals bound TIGHT to the digit makes the 0 the value of the key before it ("Failed:0
    # Passed:68" is a passing 68-test run), not a count of the noun after it.
    re.compile(r"(?i)(?<![\d.,])(?<![:=])0 (?:tests?|test cases?|examples?|specs?|"
               r"scenarios?|assertions?)\b"
               r"(?!\s+(?:failed|failing|failures?|errors?|issues?|problems?|"
               r"warnings?|skipped|remaining))"),
    re.compile(r"(?i)(?<![\d.,])(?<![:=])0 pass(?:ed|ing)\b"),
    re.compile(r"(?i)\[no test files\]"),
    re.compile(r"(?i)(?<![\d.,])(?<![:=])0 (?:files?|matches|items?|records?|lines?|paths?)"
               r" (?:were )?(?:scanned|checked|searched|examined|inspected|"
               r"processed|analysed|analyzed|linted|compared)\b"),
    re.compile(r"(?i)\b(?:scanned|checked|searched|examined|inspected|processed|"
               r"analysed|analyzed|linted|compared)\s+0 "
               r"(?:files?|matches|items?|records?|lines?|paths?)\b"),
    re.compile(r"(?i)\bno (?:input )?(?:\w+ )?files? (?:to (?:check|scan|lint|"
               r"format|process|test|analyse|analyze)\b|given\b|specified\b|"
               r"provided\b)"),
    re.compile(r"(?i)\bnothing to (?:check|scan|verify|test|analyse|analyze)\b"),
)

# Counter-evidence: a NON-ZERO count of subjects anywhere in the same output. Three forms:
# "<N> <noun>", "<noun>: <N>" / "<noun>=<N>", and the generic "<N> [distinct] <word>" / "x<N>".
# A count followed by a word naming what did NOT run or what was wrong is a count of defects or
# absence, never a measured subject ("0 passed, 3 skipped" must stay refused).
_EXCLUDED_WORDS = (r"failed|failing|failures?|errors?|issues?|problems?|warnings?|skipped|"
                   r"deselected|xfailed|xpassed|remaining|missing|left|absent")
_MEASURED_SOMETHING = re.compile(
    r"(?i)(?:"
    r"(?<![\d.,])[1-9][\d,]*\s+(?:tests?|test cases?|examples?|specs?|"
    r"scenarios?|assertions?|checks?|items?|files?|matches|results?|rows?|"
    r"records?|lines?|passed|passing|selected|collected)\b"
    r"|"
    r"\b(?:tests?|test cases?|examples?|specs?|scenarios?|assertions?|checks?|"
    r"items?|files?|matches|results?|rows?|records?|lines?|passed|passing|"
    r"selected|collected|total)\s*[:=]\s*[1-9][\d,]*\b"
    r"|"
    r"(?<![\d.,])\b[1-9][\d,]*\s+(?:distinct\s+)?"
    r"(?!(?:" + _EXCLUDED_WORDS + r")\b)\w+"
    r"|"
    r"\bx[1-9]\d*\b"
    r")")

# A needle that is only a TEST INPUT being described is not a result: inside quotes (when the
# output holds something else too), after a planted/input/probe/verify_output= marker, or
# followed by an arrow into an HTTP status ("-> 400").
_TEST_INPUT_MARKERS = re.compile(r"(?i)\b(?:planted|input|probe|verify_output\s*=)")
_TEST_INPUT_ARROW = re.compile(r"^\s*(?:->|→)\s*\d{3}\b")
_QUOTE_CHARS = "'\"`"
_CONTROL_DID_NOT_RUN = (126, 127)


def _quoted_spans(line: str) -> list:
    spans = []
    for q in _QUOTE_CHARS:
        qq = re.escape(q)
        for m in re.finditer(qq + r"([^" + qq + r"]*)" + qq, line):
            spans.append((m.start(1), m.end(1)))
    return spans


def _is_test_input_span(text: str, start: int, end: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start:line_end if line_end != -1 else len(text)]
    rel_start, rel_end = start - line_start, end - line_start
    if any(s <= rel_start and rel_end <= e for s, e in _quoted_spans(line)):
        # A quote with NOTHING else in the output is the (still vacuous) evidence itself.
        if re.sub(r"[\s'\"`]", "", text[:start] + text[end:]):
            return True
    if _TEST_INPUT_MARKERS.search(line[:rel_start]):
        return True
    return bool(_TEST_INPUT_ARROW.match(line[rel_end:]))


def first_vacuity_needle(text) -> Optional[str]:
    """The literal "this measured nothing" phrase in `text` (quoted back to the closer), or None."""
    if not isinstance(text, str):
        return None
    for pattern in _VACUOUS_PHRASES:
        for match in pattern.finditer(text):
            if not _is_test_input_span(text, match.start(), match.end()):
                return match.group(0).strip()
    return None


def measured_something(text) -> Optional[str]:
    if not isinstance(text, str):
        return None
    match = _MEASURED_SOMETHING.search(text)
    return match.group(0).strip() if match else None


def vacuity_problem(text) -> Optional[str]:
    needle = first_vacuity_needle(text)
    if not needle or measured_something(text):
        return None
    return needle


def control_problem(payload: dict) -> Optional[str]:
    """Why a supplied negative control does not license the close, or None (opt-in)."""
    cmd = payload.get("control_cmd")
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    code = payload.get("control_exit")
    if type(code) is not int:
        return (f"control_cmd {cmd.strip()!r} was supplied without an integer control_exit, "
                "so nothing is known about whether the control failed")
    if code in _CONTROL_DID_NOT_RUN:
        return (f"the negative control {cmd.strip()!r} never ran: exit {code} is the shell "
                "saying it could not run it at all, so it was not shown to fail")
    if code == 0:
        return (f"the negative control {cmd.strip()!r} was supposed to FAIL and it exited 0, "
                "so this check reports success whether the work was done or not")
    return None


_NOOP = {"true", ":", "echo", "printf", "/bin/true", "/usr/bin/true"}
_COMPOUND = re.compile(r"[;&|`]|\$\(")


def noop_command(cmd: str) -> bool:
    """A verify_cmd that cannot fail and reads nothing: a builtin no-op or a bare echo."""
    if _COMPOUND.search(cmd):
        return False
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return False
    if not argv:
        return True
    if argv[0] == "exit":
        return argv[1:] in ([], ["0"])
    return argv[0] in _NOOP


# a check that runs konstant's memory (the CLI verbs or the MCP server): memory is a hint a model
# wrote, never evidence (docs/CONCEPTS.md "Memory"); the verifier's re-run cannot reach it either
MEMORY_CMD = re.compile(r"(?:^|[\s;&|(`/])konstant(?:\s+--?[A-Za-z][\w-]*(?:[ =][^\s-]\S*)?)*"
                        r"\s+(?:mcp\s+)?memory\b")


def memory_problem(cmd) -> Optional[str]:
    if isinstance(cmd, str) and MEMORY_CMD.search(cmd):
        return (f"verify_cmd {cmd.strip()!r} reads konstant's memory: memory is never evidence "
                "(a note is what a model wrote, not what the work does); check the work itself")
    return None


def evidence_problems(payload) -> list:
    """Rule 1: every failing field, named at once."""
    if not isinstance(payload, dict):
        return ["no evidence was sent: the close needs VERIFY_CMD, VERIFY_EXIT=0 and the output"]
    out = []
    cmd = payload.get("verify_cmd")
    if not isinstance(cmd, str) or not cmd.strip():
        out.append("verify_cmd is missing: name the check that was run (a 'VERIFY_CMD: <cmd>' line)")
    elif noop_command(cmd):
        out.append(f"verify_cmd {cmd.strip()!r} checks nothing (a no-op or a bare echo exits 0 "
                   "whatever the work): name the check that was run")
    elif memory_problem(cmd):
        out.append(memory_problem(cmd))
    code = payload.get("verify_exit")
    if type(code) is not int:
        out.append("verify_exit is missing: the evidence needs a 'VERIFY_EXIT=0' line captured "
                   "from an executed check (`<cmd>; RC=$?`)")
    elif code != 0:
        out.append(f"verify_exit is {code}: a failing check never closes a job "
                   "(VERIFY_EXIT=0 required) - fix it, or block the job with the failure")
    output = payload.get("verify_output")
    if not isinstance(output, str) or not output.strip():
        out.append("verify_output is empty: paste the captured output of the check")
    return out


def cannot_fail_problem(payload) -> Optional[str]:
    """Rules 2+3 as ONE function, vacuity first (cheapest, needs no second command)."""
    if not isinstance(payload, dict):
        return None
    needle = vacuity_problem(payload.get("verify_output"))
    if needle:
        return (f"vacuous evidence: the verify_output says {needle!r} and nothing else in it "
                "reports a non-zero count of subjects, so it exited 0 having measured nothing")
    return control_problem(payload)


def _probe_command(line: str) -> str:
    body = line[len("PROBE:"):] if line.startswith("PROBE:") else line
    return body.split(" => ")[0].strip()


def self_attested(probes: list, evidence_path: str, bound: bool) -> bool:
    """True when every PROBE reads only the evidence file itself and no COMMIT=/BASE= binds work.

    Conservative: a probe naming any other path, or no path at all (a live-state read-back),
    makes the close domain-bound. Such a close proves the report exists, not the claim in it.
    """
    if not probes or bound or not evidence_path:
        return False
    real = os.path.realpath(evidence_path)
    base = os.path.basename(real)

    def is_ev(token: str) -> bool:
        if token in (evidence_path, real, base):
            return True
        try:
            return os.path.realpath(token) == real
        except (OSError, ValueError):
            return False

    for line in probes:
        cmd = _probe_command(line)
        paths = [t for t in cmd.split() if "/" in t or t.startswith("~") or t == base]
        if not paths or not all(is_ev(t) for t in paths):
            return False
    return True


def cap_output(text: str, limit: int = OUTPUT_CAP) -> str:
    raw = text.encode("utf-8")
    return text if len(raw) <= limit else raw[:limit].decode("utf-8", errors="ignore")


def check_close(payload: dict, policy) -> tuple:
    """-> (refusals, warnings, record). `record` is what is stored as evidence_json."""
    refusals, warnings = [], []

    def apply(mode: str, problems: list) -> None:
        if mode == "strict":
            refusals.extend(problems)
        elif mode == "warn":
            warnings.extend(f"(policy warn) {p}" for p in problems)

    payload = payload if isinstance(payload, dict) else {}
    apply(policy.evidence, evidence_problems(payload))
    needle = vacuity_problem(payload.get("verify_output"))
    if needle:
        apply(policy.vacuity, [cannot_fail_problem({"verify_output": payload.get("verify_output")})])
    ctrl = control_problem(payload)
    if ctrl:
        apply(policy.negative_control, [ctrl])
    probes = [p for p in payload.get("probes") or [] if isinstance(p, str)]
    bound = bool(payload.get("commit") or payload.get("base"))
    sa = self_attested(probes, str(payload.get("evidence_path") or ""), bound)
    if not (isinstance(payload.get("docs"), str) and payload["docs"].strip()):
        warnings.append("evidence has no 'DOCS:' line: name the documents this change de-staled, "
                        "or 'DOCS: n/a - <reason>'")
    if sa:
        warnings.append("SELF-ATTESTED close: every PROBE reads the evidence file itself and no "
                        "COMMIT=/BASE= binds the work; add a probe that reads the domain")
    record = {k: payload[k] for k in ("verify_cmd", "verify_exit", "control_cmd", "control_exit",
                                      "commit", "base", "docs", "evidence_path") if k in payload}
    if isinstance(payload.get("verify_output"), str):
        record["verify_output"] = cap_output(payload["verify_output"])
    record["probes"] = probes
    record["self_attested"] = sa
    return refusals, warnings, record
