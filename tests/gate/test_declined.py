"""The DECLINED marker excuses an EXCUSABLE condition only in the AND form: the claim QUOTES the
condition AND `job <id>` carries an owner-role note `DECLINED: <claim>` on a reachable board
(REVIEW F-01: free text and "any existing job" are things the close-out agent can author).
Findings of the unexcusable rules (authorship, verdicts, phases, judged, tests, verified) are
never excused."""
from __future__ import annotations

from tests.gate.conftest import SURFACES, FakeBoard, done_text

COND = "DONE.md D2 is FAIL"
CLAIM = "the cache warms up in time"


def _rows():
    return ([f"D2 | {CLAIM} | FAIL | warm-up takes 40 s"]
            + [f"S{i} | surface {s} | N/A | not touched" for i, s in enumerate(SURFACES, 1)])


def _owner(job_id, claim=CLAIM, role="owner", kind="note"):
    return FakeBoard({job_id: {"id": job_id, "trail": [
        {"role": role, "kind": kind, "actor": role, "body": f"DECLINED: {claim}"}]}})


def test_declined_green_owner_note(scen):
    s = scen().good()
    s.done(done_text(f"DECLINED | {CLAIM} | job 12\n", rows=_rows()))
    assert s.check(_owner(12))[0] == 0


def test_declined_green_owner_approval(scen):
    s = scen().good()
    s.done(done_text(f"DECLINED | {CLAIM} | job 12\n", rows=_rows()))
    assert s.check(_owner(12, kind="approval"))[0] == 0


def test_declined_red_owner_quote_is_free_text(scen):
    s = scen().good()
    s.done(done_text(f'DECLINED | {CLAIM} | owner said "the slow warm-up is fine for now"\n',
                     rows=_rows()))
    lines = s.check()[1]
    assert any(ln.startswith(COND) for ln in lines) and any("not an owner decision" in ln
                                                           for ln in lines)


def test_declined_red_note_by_another_role(scen):
    s = scen().good()
    s.done(done_text(f"DECLINED | {CLAIM} | job 12\n", rows=_rows()))
    assert any(ln.startswith(COND) for ln in s.check(_owner(12, role="orchestrator"))[1])


def test_declined_red_note_names_another_claim(scen):
    s = scen().good()
    s.done(done_text(f"DECLINED | {CLAIM} | job 12\n", rows=_rows()))
    assert any(ln.startswith(COND) for ln in s.check(_owner(12, "something else"))[1])


def test_declined_red_word_list(scen):
    s = scen().good()
    s.done(done_text("DECLINED | cache | job 12\n", rows=_rows()))
    lines = s.check(_owner(12, "cache"))[1]
    assert any(ln.startswith(COND) for ln in lines) and any("word-list" in ln for ln in lines)


def test_declined_red_claim_does_not_quote(scen):
    s = scen().good()
    s.done(done_text("DECLINED | everything else is fine here | job 12\n", rows=_rows()))
    lines = s.check(_owner(12, "everything else is fine here"))[1]
    assert any(ln.startswith(COND) for ln in lines)


def test_declined_red_unresolvable_ref(scen):
    s = scen().good()
    s.done(done_text(f"DECLINED | {CLAIM} | job 99999\n", rows=_rows()))
    assert any("not an owner decision" in ln for ln in s.check(FakeBoard({}))[1])
    assert any("not an owner decision" in ln for ln in s.check(FakeBoard(down=True))[1])
    assert any("not an owner decision" in ln for ln in s.check(offline=True)[1])


def test_declined_never_excuses_a_failing_test(scen):
    s = scen().good()
    s.write("test_more.py", "def test_broken():\n    assert 1 == 2\n")
    s.verdicts()
    s.done(done_text("DECLINED | pytest failed in the out directory | job 12\n"))
    lines = s.check(_owner(12, "pytest failed in the out directory"))[1]
    assert any(ln.startswith("pytest failed in") for ln in lines), lines


def test_declined_never_excuses_authorship(scen):
    s = scen(mode="runner").good()
    s.manifest("02-2-coder-c1", 2, "coder", created=["TEST-verdict.md"])
    claim = "AUTHORSHIP: TEST-verdict.md was written by the coder"
    s.done(done_text(f"DECLINED | {claim} | job 12\n"))
    assert any(ln.startswith("AUTHORSHIP:") for ln in s.check(_owner(12, claim))[1])
