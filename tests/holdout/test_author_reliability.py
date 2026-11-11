"""The scenario writer made reliable for one local model, the bar unchanged (wave L5-7;
docs/LEVEL5.md "L5-7 as built"). In the L5-6b live run the same model's drafts were refused by the
lint twice per job (not held out, hint leaks, a hint over 200 characters, an EXPECT_RE that matches
empty output, both or neither expectation, too few) and both jobs ended `holdout-authoring
BLOCKED`. The refusals were right, so nothing here relaxes a rule:

  - the live drafts' shapes (tests/fixtures/fake_harness.py LIVE_DRAFTS) are still refused, by the
    seal and by the new pre-check, and the pre-check's detail never changes a verdict;
  - what is new helps a model meet the bar: worked examples that pass the lint, a skeleton the
    lint refuses until it is filled, the pre-check `holdout lint --draft` run INSIDE the phase
    (no board, no store), the seal's exact reasons per draft in the retry prompt, and
    `[holdout] author_attempts` (default 3);
  - nothing a producer can read gains scenario text (the retry prompt and the pre-check's output
    live in the sealed store), and the retry prompt never carries another job's scenarios.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from konstant import config as config_mod
from konstant.holdout import draft, lint
from tests.fixtures.fake_harness import B1_BRIEF
from tests.fixtures.fake_scenario import LIVE_DRAFTS, SCENARIOS
from tests.holdout.conftest import make_ws, needs_jail

DOD = B1_BRIEF[B1_BRIEF.index("DoD:"):]
LIVE_CODES = ["NOT HELD OUT", "HINT LEAKS", "HINT", "TRIVIAL", "MALFORMED"]
TEMPCONV = ("tempconv: add a --to-celsius flag\n\nDoD:\n- `python3 -m tempconv --to-celsius 32` "
            "prints 0.0\n")


def verdicts(text: str, hid: str, brief: str = B1_BRIEF, acc: str = DOD, detail=False) -> list:
    try:
        sc = lint.parse(lint.with_canary(text.encode()), hid, detail=detail)
    except lint.ScenarioError as exc:
        return [str(exc)]
    return lint.lint(sc, brief, acc, detail=detail)


def codes(lines: list) -> list:
    return [ln.split(":", 1)[0] for ln in lines]


# --- the bar: the live drafts stay refused -------------------------------------------------------

@pytest.mark.parametrize("i", range(len(LIVE_DRAFTS)))
def test_live_drafts_are_still_refused_red(i):
    got = verdicts(LIVE_DRAFTS[i], f"H{i + 1}")
    assert got and codes(got)[0] == LIVE_CODES[i], got
    assert codes(verdicts(LIVE_DRAFTS[i], f"H{i + 1}", detail=True)) == codes(got)


def test_live_set_rules_still_refuse_too_few_and_neither_expectation_red():
    one = lint.parse(lint.with_canary(SCENARIOS[0].encode()), "H1")
    assert codes(lint.lint_set([one], 2, "2")) == ["TOO FEW"]
    neither = re.sub(r"(?m)^EXPECT_OUT:.*\n", "", SCENARIOS[0])
    assert verdicts(neither, "H1") == ["MALFORMED: H1 needs exactly one of EXPECT_OUT and "
                                       "EXPECT_RE"]


def corpus() -> list:
    base = list(LIVE_DRAFTS) + list(SCENARIOS) + [t for _w, t in draft.EXAMPLES]
    out = list(base)
    for t in base:                                   # mutations that trip one rule each
        out.append(t.replace("EXPECT_EXIT: 0", "EXPECT_EXIT: 0\nEXPECT_RE: x?"))
        out.append(re.sub(r"(?m)^RUN: .*$", "RUN: pytest -q", t))
        out.append(re.sub(r"(?m)^HINT: .*$", "HINT: python3 prints it", t))
        out.append(re.sub(r"(?m)^EXPECT_OUT: .*$", "EXPECT_OUT: hello world", t))
        out.append(t + "BOGUS: key\n")
    return out


def test_the_detail_never_changes_a_verdict():
    """detail=True only appends what tripped a rule: the same lines, the same order."""
    for i, t in enumerate(corpus()):
        plain = verdicts(t, "H1")
        rich = verdicts(t, "H1", detail=True)
        assert len(plain) == len(rich), (i, plain, rich)
        for a, b in zip(plain, rich):
            assert b == a or b.startswith(a + " ("), (i, a, b)


def test_the_detail_names_what_tripped_each_rule():
    got = {i: verdicts(t, f"H{i}", detail=True) for i, t in enumerate(LIVE_DRAFTS, 1)}
    assert "found there: 'hello world'" in got[1][0]
    assert "shared words: greet, hello, print, zoe" in got[2][0]
    assert "it has 251" in got[3][0]
    assert "found in the test string ''" in got[4][0]
    assert got[5] == ["MALFORMED: H5 needs exactly one of EXPECT_OUT and EXPECT_RE (it has both)"]


# --- the helpers: examples, skeleton, rules ------------------------------------------------------

def test_worked_examples_pass_the_lint_green():
    parsed = []
    for _why, text in draft.EXAMPLES:
        assert verdicts(text, "E", TEMPCONV, TEMPCONV[TEMPCONV.index("DoD:"):]) == []
        parsed.append(lint.parse(lint.with_canary(text.encode()), "E"))
        assert "greet" not in text.lower()            # another project: nothing to copy here
    assert {s.kind for s in parsed} == {"proof", "regression"}
    assert any(s.expect_re for s in parsed) and any(s.expect_out for s in parsed)
    assert lint.lint_set(parsed, 2, "x") == []


def test_skeleton_is_refused_until_it_is_filled_red_then_green():
    for kind in ("proof", "regression"):
        for regex in (False, True):
            sk = draft.skeleton(kind, regex)
            with pytest.raises(lint.ScenarioError, match="<FILL: ...> placeholder"):
                lint.parse(sk.encode(), "H1")
    filled = draft.skeleton("regression")
    fill = dict(ln.split(": ", 1) for ln in SCENARIOS[1].splitlines())
    filled = "\n".join(f"{ln.split(':', 1)[0]}: {fill[ln.split(':', 1)[0]]}"
                       if "<FILL:" in ln and not ln.startswith("#") else ln
                       for ln in filled.splitlines())
    sc = lint.parse(lint.with_canary(filled.encode()), "H1")
    assert sc.kind == "regression" and lint.lint(sc, B1_BRIEF, DOD) == []


def test_the_rules_text_states_the_lints_own_numbers():
    assert f"{lint.LITERAL_MIN} or more" in draft.RULES and "200 characters" in draft.RULES
    for word in ("proof", "regression", "EXPECT_OUT", "EXPECT_RE", "VACUOUS", "UNRUNNABLE",
                 "test runner"):
        assert word in draft.RULES
    from konstant.verify.probe import TRIVIAL_CANARIES
    assert len(TRIVIAL_CANARIES) == 5 and "five test strings" in draft.RULES
    assert "{need}" in draft.RULES


def test_author_attempts_is_one_config_key_with_bounds(tmp_path):
    assert config_mod.DEFAULTS["holdout"]["author_attempts"] == 3
    for bad in (0, 11):
        (tmp_path / "konstant.toml").write_text(f"[holdout]\nauthor_attempts = {bad}\n")
        with pytest.raises(config_mod.ConfigError, match="author_attempts"):
            config_mod.load(tmp_path)
    (tmp_path / "konstant.toml").write_text("[holdout]\nauthor_attempts = 5\n")
    assert config_mod.load(tmp_path).data["holdout"]["author_attempts"] == 5


def test_feedback_carries_each_drafts_reasons_name_and_text(tmp_path):
    files = {}
    for i, t in enumerate(LIVE_DRAFTS[:3], 1):
        files[f"H{i}"] = tmp_path / f"d{i}.scenario"
        files[f"H{i}"].write_text(t)
    reasons = [verdicts(t, f"H{i}")[0] for i, t in enumerate(LIVE_DRAFTS[:3], 1)]
    reasons.append("TOO FEW: job 2 would have 1 sealed scenario(s); [holdout] min_per_job = 2")
    ctx = {"job": "1.1", "brief": B1_BRIEF, "acceptance": DOD, "need": 2}
    fb = draft.feedback(reasons, files, 1, 3, ctx)
    assert fb.startswith("Attempt 1 of 3 was refused")
    for i in (1, 2, 3):
        block = fb.split(f"### d{i}.scenario (checked as H{i}): REFUSED", 1)[1].split("###")[0]
        assert f"- {reasons[i - 1]}" in block                   # the seal's exact reason
        assert LIVE_DRAFTS[i - 1].splitlines()[0] in block      # the draft as written
    assert "shared words: greet, hello, print, zoe" in fb       # the detail
    assert "### the set\n- TOO FEW" in fb


# --- the pre-check CLI: no board, no store, allowed inside a phase ----------------------------

def kcli(home: Path, *args, cwd=None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8",
           "KONSTANT_HOME": str(home), "KONSTANT_IN_TASK": "1", "KONSTANT_IDENTITY": "scenario"}
    return subprocess.run([sys.executable, "-m", "konstant", "holdout", *map(str, args)],
                          capture_output=True, text=True, env=env, cwd=str(cwd or home),
                          timeout=60)


@pytest.fixture()
def drafts(tmp_path):
    d = tmp_path / "ws" / "var" / "holdout" / "2" / "drafts"
    d.mkdir(parents=True)
    draft.write_context(d, {"display_id": "1.1", "brief": B1_BRIEF, "acceptance": DOD}, 2)
    return d


def test_lint_draft_refuses_the_live_drafts_inside_a_task_red(drafts):
    for i, t in enumerate(LIVE_DRAFTS, 1):
        (drafts / f"d{i}.scenario").write_text(t)
    res = kcli(drafts.parents[3], "lint", "--draft", ".", cwd=drafts)
    assert res.returncode == 1, res.stdout + res.stderr
    for i, code in enumerate(LIVE_CODES, 1):
        assert f"  - {code}: d{i}.scenario" in res.stdout, res.stdout
    assert "DRAFTS REFUSED" in res.stdout and "note:" not in res.stdout   # R7 was checked


def test_lint_draft_passes_a_set_that_follows_the_rules_green(drafts):
    for i, t in enumerate(SCENARIOS, 1):
        (drafts / f"d{i}.scenario").write_text(t)
    res = kcli(drafts.parents[3], "lint", "--draft", ".", "--json", cwd=drafts)
    assert res.returncode == 0, res.stdout + res.stderr
    out = json.loads(res.stdout)
    assert out["ok"] and out["held_out_checked"] and out["set"] == []
    (drafts / "d2.scenario").unlink()                              # one left: too few
    res = kcli(drafts.parents[3], "lint", "--draft", ".", cwd=drafts)
    assert res.returncode == 1 and "TOO FEW" in res.stdout


def test_lint_draft_never_reads_the_sealed_store_red_then_green(drafts):
    ws = drafts.parents[3]
    sealed = drafts.parent / "H1.scenario"
    sealed.write_text(SCENARIOS[0])
    for target in (sealed, drafts.parent, ws / "memory" / "x.scenario",
                   ws / "var" / "holdout" / "2" / "runs" / "x.scenario"):
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(SCENARIOS[0])
        res = kcli(ws, "lint", "--draft", target)
        assert res.returncode == 2 and "lies in a sealed store" in res.stderr, (target, res)
        assert "hello Ada" not in res.stdout + res.stderr
    res = kcli(ws, "lint", "--draft", ".", "--context", sealed, cwd=drafts)
    assert res.returncode == 2 and "lies in a sealed store" in res.stderr
    (drafts / "mine.scenario").write_text(SCENARIOS[0])           # green: its own draft
    res = kcli(ws, "lint", "--draft", drafts / "mine.scenario")
    assert res.returncode == 1 and "mine.scenario: ok (proof)" in res.stdout   # (too few)


def test_holdout_new_writes_a_skeleton_and_never_overwrites(drafts):
    ws = drafts.parents[3]
    res = kcli(ws, "new", "--kind", "proof", "--out", "p.scenario", cwd=drafts)
    assert res.returncode == 0, res.stderr
    assert "KIND: proof" in (drafts / "p.scenario").read_text()
    again = kcli(ws, "new", "--kind", "proof", "--out", "p.scenario", cwd=drafts)
    assert again.returncode == 2 and "never overwrites" in again.stderr
    res = kcli(ws, "lint", "--draft", "p.scenario", cwd=drafts)
    assert res.returncode == 1 and "<FILL: ...> placeholder" in res.stdout


# --- end to end: the scenario writer's phase through the real dsh adapter and jail ------------

MARK = "hello Quintessa"           # another job's sealed scenario: must reach no other prompt
OTHER = f"""SCENARIO: another job's proof
KIND: proof
RUN: python3 -c "from greeter import greet; print(greet('Quintessa'))"
EXPECT_EXIT: 0
EXPECT_OUT: {MARK}
HINT: a caller's own name is not used
"""


@pytest.fixture()
def aws(tmp_path):
    w = make_ws(tmp_path)
    try:
        yield w
    finally:
        w.stop_board()


def author(w, job: int, mode: str):
    e = w.henv(FAKE_HARNESS_MODE=mode)
    return subprocess.run([sys.executable, "-m", "konstant", "holdout", "author", str(job),
                           "--harness", "dsh", "--json"], capture_output=True, text=True,
                          env=e, cwd=str(w.home), timeout=900)


def prompts(w, job: int) -> list:
    runs = sorted((w.home / "var" / "holdout" / str(job) / "runs").iterdir())
    return [next((r / "prompts").glob("*.md")).read_text() for r in runs]


def phase_logs(w, job: int) -> list:
    runs = sorted((w.home / "var" / "holdout" / str(job) / "runs").iterdir())
    return [next((r / "phases").glob("*.log")).read_text() for r in runs]


def producer_visible(w) -> str:
    """Every file a producing phase may read that konstant writes (var/ minus the sealed
    stores and secrets), plus the board's rows: the scenario text must be in none of them."""
    out = []
    for p in (w.home / "var").rglob("*"):
        rel = p.relative_to(w.home).parts
        if p.is_file() and rel[1] not in ("holdout", "secrets", "memory", "research"):
            out.append(p.read_bytes().decode("utf-8", "replace"))
    return "\n".join(out)


@needs_jail
def test_a_refused_set_comes_back_with_its_reasons_per_draft_and_then_seals(aws):
    other = aws.add_job()
    assert aws.seal(other, OTHER, SCENARIOS[1]).returncode == 0          # job 2, sealed by owner
    job = aws.add_job()
    res = author(aws, job, "scenario-retry")
    assert res.returncode == 0, res.stderr[-3000:]
    out = json.loads(res.stdout)
    assert out["attempts"] == 2 and len(out["sealed"]) == 2
    first, second = prompts(aws, job)
    assert "## Your previous drafts were refused" not in first
    fb = second.split("## Your previous drafts were refused", 1)[1]
    assert fb.split("\n", 1)[1].startswith("Attempt 1 of 3 was refused"), fb[:300]
    for i, code in enumerate(LIVE_CODES[:4], 1):                    # the seal's exact reasons
        assert f"### draft{i}.scenario (checked as H{i}): REFUSED\n- {code}: H{i}" in fb, fb
    assert "### draft5.scenario (checked as H5): REFUSED\n- MALFORMED: H5" in fb
    assert "shared words: greet, hello, print, zoe" in fb and "found there: 'hello world'" in fb
    log = phase_logs(aws, job)[1]
    assert "scenario-feedback: - HINT LEAKS: H2" in log            # the writer was given them
    for p in (first, second):                                       # never another job's set
        assert MARK not in p and "Quintessa" not in p
        assert not re.search(r"khc-[0-9a-f]{20}", p)
    stderr = res.stderr                                             # konstant's own log line
    assert "drafts refused: NOT HELD OUT: H1" in stderr
    for leak in ("Zoe", "hello Kim", "names given are used", "shared words", "found there",
                 "as you wrote it"):
        assert leak not in stderr, leak
        assert leak not in producer_visible(aws), leak
    trail = aws.json("job", "show", str(job), "--trail")["trail"]
    assert "Zoe" not in json.dumps(trail)


@needs_jail
@pytest.mark.parametrize("wrapper", [False, True])
def test_the_writer_runs_the_pre_check_inside_its_phase_and_seals_first_time(aws, wrapper):
    if wrapper:                       # an installed workspace: the prompt names its bin/konstant
        w = aws.home / "bin" / "konstant"
        w.parent.mkdir(exist_ok=True)
        w.write_text(f"#!/bin/sh\nexec {sys.executable} -m konstant \"$@\"\n")
        w.chmod(0o755)
    job = aws.add_job()
    res = author(aws, job, "scenario-lint")
    assert res.returncode == 0, res.stderr[-3000:]
    assert json.loads(res.stdout)["attempts"] == 1
    lint_line = [ln for ln in prompts(aws, job)[0].splitlines() if ln.startswith("KONSTANT-LINT:")]
    assert lint_line == [f"KONSTANT-LINT: {aws.home / 'bin' / 'konstant'} holdout lint --draft ."
                         if wrapper else
                         f"KONSTANT-LINT: {sys.executable} -m konstant holdout lint --draft ."]
    log = phase_logs(aws, job)[0]
    runs = [ln for ln in log.splitlines() if ln.startswith("scenario-lint: rc=")]
    assert runs == ["scenario-lint: rc=1", "scenario-lint: rc=0"], log[-3000:]
    assert "HINT LEAKS: proof.scenario" in log and "shared words: ada, greet" in log
    assert "scenario-lint: new rc=0" in log and "DRAFTS OK: 2 draft(s), 1 proof(s)" in log
    assert "lies in a sealed store" not in log                      # its own drafts are allowed
    assert "Ada" not in producer_visible(aws)


@needs_jail
@pytest.mark.parametrize("attempts", [None, 2])
def test_author_attempts_bounds_the_retries_and_blocks_red(aws, attempts):
    if attempts:
        toml = aws.home / "konstant.toml"
        toml.write_text(toml.read_text() + f"\n[holdout]\nauthor_attempts = {attempts}\n")
    job = aws.add_job()
    res = author(aws, job, "scenario-live")
    n = attempts or 3
    assert res.returncode == 4, res.stderr[-3000:]
    assert f"refused {n} time(s)" in res.stderr
    assert len(prompts(aws, job)) == n
    assert all(f"Attempt {k} of {n} was refused" in p for k, p in enumerate(prompts(aws, job)[1:],
                                                                            1))
    assert aws.json("job", "show", str(job))["holdouts"] == []
