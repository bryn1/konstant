"""PROBE lines: parsing, the allowlist gate, and execution of one line (DESIGN §7 steps 2-3).

    PROBE: <command> => <regex>
    PROBE-REFUSED: <command> => <expect> => <reason regex>

Split on the LAST ` => `. A non-match is a CONTRADICTION; a refusal, timeout or error is
UNVERIFIABLE (the row's `error` is set). `check_line` only judges a line, it never runs anything.
"""
from __future__ import annotations

import re
import shlex
import subprocess

from konstant.verify import native
from konstant.verify.shapes import Plan, Roots, parse_command

SEP = " => "
OUTPUT_CAP = native.OUTPUT_CAP
TAG_PROBE, TAG_REFUSED = "PROBE:", "PROBE-REFUSED:"
KIND_PROBE, KIND_REFUSED = "probe", "expected-refusal"
_ANY = re.compile(r"(?m)^[ \t>*-]*(PROBE(?:-REFUSED)?):\s*(.+?)\s*$")
_BLOB_EXPECT = re.compile(r"\^sha256: (?:[0-9a-f]{64}|\[0-9a-f\]\{64\})")

# A regex that matches any of these proves nothing about the state the command reads.
TRIVIAL_CANARIES = ("", " ", "x",
                    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    "!\"#%&'()*+,-./:;<=>?@[]^_`{|}~",
                    "probe-canary: no such file or directory")


def trivial_expect(expect: str) -> bool:
    try:
        rx = re.compile(expect, re.M)
    except re.error:
        return True
    return any(rx.search(c) is not None for c in TRIVIAL_CANARIES)


def _one(tag: str, body: str) -> str:
    return f"{TAG_PROBE if tag == 'PROBE' else TAG_REFUSED} {body}"


def probe_lines(text: str) -> list:
    """Every PROBE / PROBE-REFUSED line of `text`, normalised to `TAG: body`, in order, de-duplicated."""
    seen, out = set(), []
    for tag, body in _ANY.findall(text or ""):
        line = _one(tag, body)
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _untag(line: str):
    line = line.strip()
    if line.startswith(TAG_REFUSED):
        return KIND_REFUSED, line[len(TAG_REFUSED):].strip()
    if line.startswith(TAG_PROBE):
        line = line[len(TAG_PROBE):]
    return KIND_PROBE, line.strip()


def _need_regex(expect: str, what: str = "expectation") -> None:
    try:
        re.compile(expect)
    except re.error as exc:
        raise ValueError(f"{what} is not a regex: {exc}") from exc
    if trivial_expect(expect):
        raise ValueError(f"trivial {what} /{expect}/: it also matches empty or unrelated output, "
                         "so it proves nothing - anchor it to the value the row needs "
                         "(e.g. ^active$, ^0$)")


def parse(body: str, roots: Roots) -> tuple:
    """`<command> => <regex>` -> (Plan, expect). ValueError names the refusal."""
    if body.endswith(" =>"):
        body += " "                       # an empty expectation is trivial, not "missing"
    if SEP not in body:
        raise ValueError(f"no '{SEP.strip()}' expectation (PROBE: <command> => <regex>)")
    cmd, expect = body.rsplit(SEP, 1)
    plan = parse_command(cmd, roots)      # control chars / metacharacters / shape / roots
    _need_regex(expect)
    if plan.name == "blob" and not _BLOB_EXPECT.match(expect):
        raise ValueError("a blob-sha256 expectation must begin ^sha256: <64 hex>: the output also "
                         "echoes the commit and path, so a looser regex could match the echo")
    return plan, expect


def _split_refused(body: str) -> tuple:
    if SEP not in body or SEP not in body.rsplit(SEP, 1)[0]:
        raise ValueError(f"an expected refusal needs two '{SEP.strip()}' "
                         "(PROBE-REFUSED: <command> => <expect> => <reason regex>)")
    inner, reason = body.rsplit(SEP, 1)
    try:
        re.compile(reason)
    except re.error as exc:
        raise ValueError(f"the reason is not a regex: {exc}") from exc
    if trivial_expect(reason):
        raise ValueError(f"trivial reason /{reason}/: it also matches empty or unrelated text, "
                         "so it proves nothing")
    return inner, reason


def check_line(line: str, roots: Roots):
    """The refusal reason for one probe line, or None when it would run. Never runs anything.
    Accepts `PROBE: ...`, `PROBE-REFUSED: ...` or a bare `<command> => <regex>`."""
    kind, body = _untag(line)
    try:
        if kind == KIND_REFUSED:
            inner, _reason = _split_refused(body)
            try:
                parse(inner, roots)
            except ValueError:
                return None
            return "the allowlist ACCEPTS the inner line: a PROBE-REFUSED asserting it is refused is false"
        parse(body, roots)
    except ValueError as exc:
        return str(exc)
    return None


def _row(line: str, kind: str, source: str) -> dict:
    return {"line": line, "source": source, "kind": kind, "argv": None, "expect": None,
            "rc": None, "output": "", "matched": False, "error": None}


def verdict_of(row: dict) -> str:
    """matched | contradiction | unverifiable"""
    if row.get("error"):
        return "unverifiable"
    return "matched" if row.get("matched") else "contradiction"


def run_line(line: str, roots: Roots, source: str = "dod", timeout: float = 20,
             runner=subprocess.run) -> dict:
    """Judge and, when allowed, execute ONE probe line. Never raises."""
    kind, body = _untag(line)
    row = _row(line, kind, source)
    if kind == KIND_REFUSED:
        return _expected_refusal(row, body, roots)
    try:
        plan, expect = parse(body, roots)
    except ValueError as exc:
        row["error"] = f"refused: {exc}"
        return row
    row.update(argv=plan.argv, expect=expect)
    try:
        rc, out = _execute(plan, timeout, runner)
    except (subprocess.TimeoutExpired, TimeoutError):
        row["error"] = f"timeout after {timeout}s"
        return row
    except OSError as exc:
        row["error"] = f"could not run: {exc}"
        return row
    out = out[:OUTPUT_CAP]
    row.update(rc=rc, output=out, matched=re.search(expect, out, re.M) is not None)
    if plan.name == "blob" and (rc != 0 or not out.startswith("sha256: ")):
        row.update(matched=False, error=f"committed blob unreadable (rc {rc})")
    return row


def _expected_refusal(row: dict, body: str, roots: Roots) -> dict:
    try:
        inner, reason = _split_refused(body)
    except ValueError as exc:
        row["error"] = f"refused: {exc}"
        return row
    row["expect"] = reason
    try:
        plan, _expect = parse(inner, roots)
    except ValueError as exc:
        text = f"refused: {exc}"
        row.update(refused=True, output=text, matched=re.search(reason, text, re.M) is not None)
        return row
    row.update(refused=False, argv=plan.argv, matched=False,
               output="CONTRADICTION: the allowlist ACCEPTS this line (it would run: "
                      f"{shlex.join(plan.argv)[:200]}); it was NOT run")
    return row


def _execute(plan: Plan, timeout: float, runner) -> tuple:
    if plan.native:
        kind, args = plan.native
        fn = {"test": native.exists, "curl": native.curl, "sqlite": native.sqlite_select,
              "blob": native.blob_sha256}[kind]
        return fn(*args) if kind == "test" else fn(*args, timeout)
    proc = runner(plan.run, capture_output=True, text=True, timeout=timeout, env=plan.env,
                  cwd=plan.cwd, stdin=subprocess.DEVNULL, errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
