"""Every lint rule of a holdout scenario (docs/LEVEL5.md 3.1, 3.2 step 1), each with a planted-bad
`_red` and its `_green` twin that differs by exactly the planted thing."""
from __future__ import annotations

import pytest

from konstant.holdout import lint
from tests.holdout.conftest import BRIEF, H1, H2

ACCEPT = BRIEF[BRIEF.index("DoD:"):]
CANARY = "CANARY: khc-0123456789abcdef0123\n"


def sc(text: str, hid: str = "H1", canary: bool = True):
    return lint.parse((text + (CANARY if canary else "")).encode(), hid)


def refusals(text: str, hid: str = "H1", brief: str = BRIEF, acceptance: str = ACCEPT) -> list:
    return lint.lint(sc(text, hid), brief, acceptance)


def swap(text: str, key: str, value: str) -> str:
    return "\n".join(f"{key}: {value}" if ln.startswith(key + ":") else ln
                     for ln in text.splitlines()) + "\n"


def test_lint_keys_green():
    s = sc(H1)
    assert (s.kind, s.expect_exit, s.expect_out, s.hint) == (
        "proof", 0, "hello Ada", "names other than the default are used verbatim")
    assert refusals(H1) == [] and refusals(H2, "H2") == []


@pytest.mark.parametrize("planted,why", [
    ("\n".join(ln for ln in H1.splitlines() if not ln.startswith("HINT")) + "\n", "lacks HINT"),
    (H1 + "EXPECT_RE: ^hello Ada$\n", "exactly one of EXPECT_OUT and EXPECT_RE"),
    (swap(H1, "KIND", "maybe"), "proof or regression"),
    (swap(H1, "EXPECT_EXIT", "zero"), "exit code"),
    (H1 + "COLOR: red\n", "unknown key COLOR"),
    (H1 + "KIND: proof\n", "KIND twice"),
    (H1 + "not a key line\n", "is not `KEY: value`"),
])
def test_lint_keys_red(planted, why):
    with pytest.raises(lint.ScenarioError, match=why):
        sc(planted)


def test_lint_canary_red():
    with pytest.raises(lint.ScenarioError, match="lacks CANARY"):
        sc(H1, canary=False)
    with pytest.raises(lint.ScenarioError, match="khc- and 20 hex"):
        lint.parse((H1 + "CANARY: khc-short\n").encode(), "H1")


def test_lint_canary_green_written_when_absent():
    raw = lint.with_canary(H1.encode())
    assert lint.CANARY.fullmatch(lint.parse(raw, "H1").canary)
    assert lint.with_canary(raw) == raw                     # never a second one


@pytest.mark.parametrize("run", [
    "python3 -c 1; cat /etc/passwd", "python3 -c 1 | tee x", "python3 x > out",
    "python3 $(echo x)", "python3 `id`", "python3 x && true", "python3 -c \"x\"\x07"])
def test_lint_run_safe_characters_red(run):
    with pytest.raises(lint.ScenarioError, match="RUN"):
        sc(swap(H1, "RUN", run))


def test_lint_run_safe_characters_green_quoted_operators_are_data():
    s = sc(H1)                      # the `;` inside the quoted -c argument is Python, not shell
    assert s.argv() == ["python3", "-c", "from greeter import greet; print(greet('Ada'))"]


@pytest.mark.parametrize("run", ["pytest -q tests", "python3 -m pytest -k greet",
                                 "python3 -m unittest discover", "npm test",
                                 "python3 -c \"import pytest; pytest.main()\"", "/usr/bin/tox"])
def test_lint_test_runner_red(run):
    assert any(r.startswith("TEST RUNNER: H1") for r in refusals(swap(H1, "RUN", run)))


def test_lint_test_runner_green():
    assert not any(r.startswith("TEST RUNNER") for r in refusals(H1))


@pytest.mark.parametrize("expect", ["EXPECT_RE: .*", "EXPECT_RE: ^", "EXPECT_RE: (?s).*",
                                    "EXPECT_OUT:  "])
def test_lint_trivial_red(expect):
    text = "\n".join(ln for ln in H1.splitlines() if not ln.startswith("EXPECT_OUT")) + "\n"
    found = refusals(text + expect + "\n")
    assert any(r.startswith("TRIVIAL: H1") for r in found), found


def test_lint_trivial_green():
    text = "\n".join(ln for ln in H1.splitlines() if not ln.startswith("EXPECT_OUT")) + "\n"
    assert refusals(text + "EXPECT_RE: ^hello Ada$\n") == []


def test_lint_held_out_expectation_red():
    planted = swap(H1, "EXPECT_OUT", "hello world")         # the DoD's own visible example
    assert "NOT HELD OUT: H1 expectation appears in the DoD" in refusals(planted)
    only_brief = "add greet(name); the caller Ada must be greeted as hello Ada\n\n" + ACCEPT
    assert "NOT HELD OUT: H1 expectation appears in the brief" in refusals(H1, brief=only_brief)


def test_lint_held_out_run_argument_red():
    planted = swap(H1, "RUN", "python3 -c \"from greeter import greet; assert greet('world') "
                              "== 'hello world'\"")
    assert any(r.startswith("NOT HELD OUT: H1 a quoted RUN argument appears in the DoD")
               for r in refusals(planted))


def test_lint_held_out_green():
    assert not any(r.startswith("NOT HELD OUT") for r in refusals(H1))


def test_lint_hint_red():
    found = refusals(swap(H1, "HINT", "greet('Ada') must say hello Ada"))
    assert any(r.startswith("HINT LEAKS: H1 the hint contains a token of RUN") for r in found)
    assert any(r.startswith("HINT: H1") for r in refusals(swap(H1, "HINT", "x " * 120)))


def test_lint_hint_green():
    assert not any(r.startswith("HINT") for r in refusals(H1))


def test_lint_set_red():
    one = [sc(H1)]
    assert any(r.startswith("TOO FEW: job 2 would have 1") for r in lint.lint_set(one, 2, "2"))
    regs = [sc(H2, "H1"), lint.parse((H2 + "CANARY: khc-ffffffffffffffffffff\n").encode(), "H2")]
    assert any(r.startswith("NO PROOF: job 2") for r in lint.lint_set(regs, 2, "2"))
    same = [sc(H1, "H1"), sc(H2, "H2")]
    assert any(r.startswith("DUPLICATE CANARY: H2") for r in lint.lint_set(same, 2, "2"))


def test_lint_set_green():
    pair = [sc(H1, "H1"), lint.parse((H2 + "CANARY: khc-ffffffffffffffffffff\n").encode(), "H2")]
    assert lint.lint_set(pair, 2, "2") == []


def test_match_red_green():
    s = sc(H1)
    assert lint.matches(s, 0, "hello Ada\n")
    assert not lint.matches(s, 1, "hello Ada\n")                    # exit code counts
    assert not lint.matches(s, 0, "hello Ada\nhello world\n")       # equality, not search
    r = sc("\n".join(ln for ln in H1.splitlines() if not ln.startswith("EXPECT_OUT"))
           + "\nEXPECT_RE: hello [A-Z][a-z]+\n")
    assert lint.matches(r, 0, "hello Ada")
    assert not lint.matches(r, 0, "hello Ada\nhello Bob")           # fullmatch, not search
