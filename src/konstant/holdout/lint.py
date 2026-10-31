"""Holdout scenario files: parse and lint (docs/LEVEL5.md 3.1, 3.2 step 1). Deterministic.

One scenario per file. `KEY: value` lines; a line starting with `#` and a blank line are
ignored; a value runs to the end of its line (no inline comments, so an expectation may hold #):

    SCENARIO: greet uses the caller's name
    KIND: proof
    RUN: python3 -c "from greeter import greet; print(greet('Ada'))"
    EXPECT_EXIT: 0
    EXPECT_OUT: hello Ada
    HINT: names other than the default are used verbatim
    CANARY: khc-6c1d0f0e9b2a47d8a3f5

KIND proof: must FAIL on the base (before the work); regression: must PASS before and after.
EXPECT_OUT is the whole stripped stdout; EXPECT_RE (instead) must fullmatch the whole stripped
stdout. RUN is split with shlex and runs as an argv, never through a shell: a control character
or a shell operator (; & | < > ` $) outside quotes is refused, and so is a test runner (a
project's conftest or plugins could rewrite its verdict). CANARY (khc- + 20 hex) is the salt of
the commitment and the marker of the leak scan; `holdout add` writes one when the file has none.
The lint never prints a scenario's content, only its id and the rule.
"""
from __future__ import annotations

import re
import secrets
import shlex
from dataclasses import dataclass

from konstant.verify.probe import trivial_expect

KEYS = ("SCENARIO", "KIND", "RUN", "EXPECT_EXIT", "EXPECT_OUT", "EXPECT_RE", "HINT", "CANARY")
REQUIRED = ("SCENARIO", "KIND", "RUN", "EXPECT_EXIT", "HINT", "CANARY")
KINDS = ("proof", "regression")
CANARY = re.compile(r"khc-[0-9a-f]{20}")
_LINE = re.compile(r"^([A-Z_]+):[ \t]?(.*)$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
LITERAL_MIN = 4
RUNNER_BINS = {"pytest", "py.test", "nose2", "nosetests", "tox", "nox", "jest", "mocha", "vitest",
               "rspec", "phpunit", "ctest", "behave", "ava", "karma", "trial"}
RUNNER_PAIRS = {("npm", "test"), ("yarn", "test"), ("pnpm", "test"), ("bun", "test"),
                ("deno", "test"), ("go", "test"), ("cargo", "test"), ("make", "test"),
                ("make", "check"), ("mvn", "test"), ("gradle", "test"), ("dotnet", "test"),
                ("-m", "pytest"), ("-m", "unittest"), ("-m", "nose2"), ("-m", "doctest")}
RUNNER_WORD = re.compile(r"\b(pytest|unittest|nose2|doctest)\b")
STOP = {"the", "and", "for", "not", "are", "was", "with", "that", "this", "from", "into", "than",
        "then", "its", "has", "have", "when", "what", "all", "any", "one", "but", "use"}


class ScenarioError(ValueError):
    """A scenario file that does not parse; the message names the rule, never the content."""


@dataclass
class Scenario:
    hid: str
    fields: dict
    raw: bytes

    kind = property(lambda self: self.fields["KIND"])
    run = property(lambda self: self.fields["RUN"])
    hint = property(lambda self: self.fields["HINT"])
    canary = property(lambda self: self.fields["CANARY"])
    expect_out = property(lambda self: self.fields.get("EXPECT_OUT"))
    expect_re = property(lambda self: self.fields.get("EXPECT_RE"))

    @property
    def expect_exit(self) -> int:
        return int(self.fields["EXPECT_EXIT"])

    def argv(self) -> list:
        return run_argv(self.run, self.hid)

    def expectation(self) -> str:
        return self.expect_out if self.expect_out is not None else self.expect_re


def new_canary() -> str:
    return "khc-" + secrets.token_hex(10)


def with_canary(raw: bytes) -> bytes:
    """The file with a fresh CANARY line appended when it has none (the owner's convenience)."""
    text = raw.decode("utf-8", "replace")
    if any(_LINE.match(ln) and ln.startswith("CANARY:") for ln in text.splitlines()):
        return raw
    return (text.rstrip("\n") + f"\nCANARY: {new_canary()}\n").encode("utf-8")


def parse(raw: bytes, hid: str) -> Scenario:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ScenarioError(f"MALFORMED: {hid} is not UTF-8 text") from None
    fields: dict = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            raise ScenarioError(f"MALFORMED: {hid} line {n} is not `KEY: value`")
        key, value = m.group(1), m.group(2).strip()
        if key not in KEYS:
            raise ScenarioError(f"MALFORMED: {hid} line {n}: unknown key {key} "
                                f"(keys: {', '.join(KEYS)})")
        if key in fields:
            raise ScenarioError(f"MALFORMED: {hid} has {key} twice")
        fields[key] = value
    missing = [k for k in REQUIRED if not fields.get(k)]
    if missing:
        raise ScenarioError(f"MALFORMED: {hid} lacks {', '.join(missing)}")
    if ("EXPECT_OUT" in fields) == ("EXPECT_RE" in fields):
        raise ScenarioError(f"MALFORMED: {hid} needs exactly one of EXPECT_OUT and EXPECT_RE")
    if fields["KIND"] not in KINDS:
        raise ScenarioError(f"MALFORMED: {hid} KIND must be proof or regression")
    if not re.fullmatch(r"\d{1,3}", fields["EXPECT_EXIT"]) or int(fields["EXPECT_EXIT"]) > 255:
        raise ScenarioError(f"MALFORMED: {hid} EXPECT_EXIT must be an exit code 0-255")
    if not CANARY.fullmatch(fields["CANARY"]):
        raise ScenarioError(f"MALFORMED: {hid} CANARY must be khc- and 20 hex digits")
    sc = Scenario(hid, fields, raw)
    sc.argv()
    if sc.expect_re is not None:
        try:
            re.compile(sc.expect_re)
        except re.error:
            raise ScenarioError(f"MALFORMED: {hid} EXPECT_RE is not a regex") from None
    return sc


def run_argv(run: str, hid: str = "H?") -> list:
    """RUN as an argv (shlex, no shell). Refused: control characters anywhere, and shell
    operators or substitutions outside quotes (they would mean nothing without a shell)."""
    if _CONTROL.search(run):
        raise ScenarioError(f"MALFORMED: {hid} RUN carries a control character")
    quote = ""
    for i, ch in enumerate(run):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch in ";&|<>`$" and not (i and run[i - 1] == "\\"):
            raise ScenarioError(f"MALFORMED: {hid} RUN has a shell operator outside quotes: it "
                                "runs as an argv, never through a shell")
    try:
        argv = shlex.split(run)
    except ValueError:
        raise ScenarioError(f"MALFORMED: {hid} RUN does not split (unbalanced quotes)") from None
    if not argv:
        raise ScenarioError(f"MALFORMED: {hid} RUN is empty")
    return argv


def matches(sc: Scenario, rc: int, stdout: str) -> bool:
    """Exit code AND the whole stripped stdout (equality, or a regex fullmatch)."""
    out = stdout.strip()
    if rc != sc.expect_exit:
        return False
    if sc.expect_out is not None:
        return out == sc.expect_out
    return re.fullmatch(sc.expect_re, out) is not None


def _quoted(text: str) -> list:
    out = []
    for a, b in re.findall(r"'([^']*)'|\"([^\"]*)\"", text):
        out.append(a or b)
    return out


def expectation_literals(sc: Scenario) -> list:
    exp = [sc.expect_out] if sc.expect_out is not None else \
        re.split(r"\\[A-Za-z]|[\\^$.|?*+()\[\]{}]", sc.expect_re)
    return [x for x in dict.fromkeys(s.strip() for s in exp) if len(x) >= LITERAL_MIN]


def run_literals(sc: Scenario) -> list:
    out = []
    for q in _quoted(sc.run):
        out += [q] + _quoted(q)
    return [x for x in dict.fromkeys(s.strip() for s in out) if len(x) >= LITERAL_MIN]


def literals(sc: Scenario) -> list:
    """The distinctive literals (>= 4 chars) of the expectation and of RUN's quoted arguments:
    what a producer that teaches to the test would copy into its code (leak.py)."""
    return list(dict.fromkeys(expectation_literals(sc) + run_literals(sc)))


def _words(text: str) -> set:
    return {w.lower() for w in re.findall(r"[A-Za-z0-9_]{3,}", text or "")} - STOP


def lint(sc: Scenario, brief: str, acceptance: str) -> list:
    """Refusal lines for one parsed scenario (empty: it passes the lint)."""
    out = []
    if sc.expect_out is not None and not sc.expect_out.strip():
        out.append(f"TRIVIAL: {sc.hid} the expectation is empty: it proves nothing")
    if sc.expect_re is not None and trivial_expect(sc.expect_re):
        out.append(f"TRIVIAL: {sc.hid} EXPECT_RE also matches empty or unrelated output")
    argv = sc.argv()
    bins = [a.rsplit("/", 1)[-1].lower() for a in argv]
    if (set(bins) & RUNNER_BINS or set(zip(bins, bins[1:])) & RUNNER_PAIRS
            or any(RUNNER_WORD.search(a) for a in argv[1:])):
        out.append(f"TEST RUNNER: {sc.hid} RUN calls a test runner: a holdout drives the "
                   "product's own interface (a project's test config could rewrite a runner's "
                   "verdict)")
    for what, found in (("expectation", expectation_literals(sc)),
                        ("a quoted RUN argument", run_literals(sc))):
        if any(x in (acceptance or "") for x in found):
            out.append(f"NOT HELD OUT: {sc.hid} {what} appears in the DoD")
        elif any(x in (brief or "") for x in found):
            out.append(f"NOT HELD OUT: {sc.hid} {what} appears in the brief")
    if len(sc.hint) > 200:
        out.append(f"HINT: {sc.hid} the hint is over 200 characters")
    if _words(sc.hint) & (_words(sc.run) | _words(sc.expectation())):
        out.append(f"HINT LEAKS: {sc.hid} the hint contains a token of RUN or of the "
                   "expectation (a failing holdout reveals its hint)")
    return out


def lint_set(scenarios: list, min_per_job: int, job: str) -> list:
    """The set rules over the sealed scenarios plus the batch being added."""
    out = []
    if len(scenarios) < min_per_job:
        out.append(f"TOO FEW: job {job} would have {len(scenarios)} sealed scenario(s); "
                   f"[holdout] min_per_job = {min_per_job} (add them together: --file A "
                   "--file B)")
    if scenarios and not any(s.kind == "proof" for s in scenarios):
        out.append(f"NO PROOF: job {job} needs at least one proof scenario (one that fails "
                   "before the work)")
    seen: dict = {}
    for s in scenarios:
        if s.canary in seen:
            out.append(f"DUPLICATE CANARY: {s.hid} reuses the canary of {seen[s.canary]}")
        seen.setdefault(s.canary, s.hid)
    return out
