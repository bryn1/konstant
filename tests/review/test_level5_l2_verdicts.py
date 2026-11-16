"""Wave L5-L2: how konstant identifies a verdict file (DESIGN 6.4, LEVEL5 "L5-L2 as built").

Live run L5-L run 2, attempt 2: the closing architect wrote its evidence where its prompt told it
to, into its own private dir, under the name `verify-arch/a5-verdict-prejudge.md`. Every file
named *verdict*.md anywhere under OUT was a verdict, so the check refused it as a malformed
verdict, routed it to a verifier "A5" that does not exist, and the authorship rule called it a
forgery: the attempt ended UNMET with nothing wrong in the deliverable.

The rule now: a verdict file is a *verdict*.md file DIRECTLY in OUT (konstant reads a phase's
verdict only from `OUT/<its catalog name>`); a file in a subdirectory is evidence whatever its
name and is in every pin that covers its place; a private dir is written only by its owner, which
the authorship rule proves from the phase manifests, not from names. Each attack the old
name-based rule stopped is a test below that must stay refused: forging another phase's verdict
at the top level, shadowing it from a private or a shared subdirectory, planting evidence in a
verifier's private dir, editing a verdict-named evidence file after it was judged."""
from __future__ import annotations

import os
import subprocess
import sys

from tests.holdout.conftest import needs_jail

T, R, A = "TEST-verdict.md", "REVIEW-verdict.md", "ARCH-verdict.md"
PREJUDGE = "verify-arch/a5-verdict-prejudge.md"
FAKE = f"{sys.executable} {os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'fake_harness.py')} {{prompt_file}}"


def scoped(s, name: str, word: str = "PASS", where: str = ""):
    from konstant.gate.rules import judged
    return s.write(where or name, f"findings: checked\n# JUDGED: {judged.judge(s.rec, name)}\n"
                                  f"# VERDICT: {word}\n")


def manifests(s, coder=(), reviewer=(), arch=(), tester=()):
    """The phase manifests of one code run: architect, coder, tester || reviewer (one shared
    snapshot), closing architect. Each list adds what that phase run created."""
    group = {"group_verdicts": [T, R]}
    s.manifest("01-1-architect-c1", 1, "architect")
    s.manifest("02-2-coder-c1", 2, "coder", created=["test_greet.py", *coder])
    shared = [T, R, *tester, *reviewer]
    s.manifest("03-3-tester-c1", 3, "tester", verdict=T, created=shared, **group)
    s.manifest("03-4-reviewer-c1", 4, "reviewer", verdict=R, created=shared, **group)
    s.manifest("04-5-architect-c1", 5, "architect", verdict=A, created=[A, *arch])


def built(scen, tester_word: str = "PASS"):
    s = scen(mode="runner")
    s.deliverable()
    scoped(s, T, tester_word)
    scoped(s, R)
    return s


def lines_of(s) -> tuple:
    code, lines, _w, _f = s.check()
    return code, lines


# --- the live shape -----------------------------------------------------------------------------

def test_live_a_verdict_named_evidence_file_in_the_verifiers_own_dir_is_evidence_red(scen):
    """Red on 237521d: `verify-arch/a5-verdict-prejudge.md does not END with a '# VERDICT'
    line` (owner verifier:A5-verdict.md) and `AUTHORSHIP: ... tainted`."""
    s = built(scen)
    s.write(PREJUDGE, "# pre-judgement\nauthorship and verdict-format findings: none\n")
    scoped(s, A)
    s.done()
    manifests(s, arch=[PREJUDGE])
    code, lines = lines_of(s)
    assert code == 0, lines


def test_live_the_evidence_file_is_pinned_by_its_owner_red(scen):
    """It is evidence, so its owner's pin covers it: an edit after the architect judged stales
    the architect's verdict (red on 237521d: verdict-named files were outside every pin)."""
    s = built(scen)
    s.write(PREJUDGE, "first pass\n")
    scoped(s, A)
    s.write(PREJUDGE, "rewritten after the pin\n")
    s.done()
    manifests(s, arch=[PREJUDGE])
    found = [f.text for f in s.check()[3] if f.rule == "judged"]
    assert any(t.startswith(f"{A} judged a different deliverable state") and PREJUDGE in t
               for t in found), found


@needs_jail
def test_live_runner_a_verifier_may_name_its_evidence_anything_red(hws):  # noqa: F811
    """The whole runner, jailed: every scoped verifier writes `a5-verdict-<agent>-prejudge.md`
    into its own dir; the run is MET on its first round, with no re-run and no AUTHORSHIP."""
    res, rd = hws.task_run("verdict-evidence", job=hws.add_job())
    assert res.returncode == 0, res.stderr[-3000:]
    assert "AUTHORSHIP" not in res.stderr and "resume" not in res.stderr, res.stderr[-3000:]
    import json
    out = json.loads((rd / "record.json").read_text())["out"]
    assert os.path.isfile(os.path.join(out, "verify-arch", "a5-verdict-architect-prejudge.md"))


# --- the attacks the rule must still stop -------------------------------------------------------

def test_attack_a_forged_top_level_verdict_still_taints(scen):
    """The closing architect writes the tester's next-cycle verdict at OUT's top level. (Inside
    the tester || reviewer group one shared snapshot credits a verdict file by NAME, as before;
    the jail keeps a member to its own files there.)"""
    s = built(scen, "FAIL")
    scoped(s, T, "PASS", where="TEST-verdict-c2.md")
    scoped(s, A)
    s.done()
    manifests(s, arch=["TEST-verdict-c2.md"])
    code, lines = lines_of(s)
    assert code == 3 and any(ln.startswith("AUTHORSHIP: TEST-verdict-c2.md") and "5-architect" in ln
                             for ln in lines), lines


def test_attack_an_off_target_verdict_inside_the_parallel_group_taints_red(scen):
    """The reviewer, inside the tester || reviewer group, writes the tester's NEXT-cycle verdict
    at OUT's top level. konstant named only TEST-verdict.md for that group, so TEST-verdict-c2.md
    is nobody's target. Red on 237521d: MET (exit 0) - the shared snapshot credited it to the
    tester by its stem and the forged PASS decided over the tester's FAIL."""
    s = built(scen, "FAIL")
    scoped(s, T, "PASS", where="TEST-verdict-c2.md")
    scoped(s, A)
    s.done()
    manifests(s, reviewer=["TEST-verdict-c2.md"])
    code, lines = lines_of(s)
    assert code == 3 and any(ln.startswith("AUTHORSHIP: TEST-verdict-c2.md") for ln in lines), \
        lines


def test_attack_a_verdict_shadowed_from_a_private_dir_never_counts_red(scen):
    """The reviewer drops a PASS named like the tester's cycle-9 verdict into its OWN dir: it is
    not a verdict, so the tester's FAIL still decides. Red on 237521d: MET (exit 0) - the file
    was the tester's decisive verdict by its name, and inside the tester || reviewer group the
    shared snapshot credited it to the tester by that same name, so even the jail (which lets the
    reviewer write its own dir) did not stop a reviewer overriding the tester's FAIL."""
    s = built(scen, "FAIL")
    scoped(s, T, "PASS", where="verify-review/TEST-verdict-c9.md")
    scoped(s, R)                                   # the reviewer pins its own dir with it
    scoped(s, A)
    s.done()
    manifests(s, reviewer=["verify-review/TEST-verdict-c9.md"])
    code, lines = lines_of(s)
    assert code == 3, lines
    assert any(ln.startswith(f"{T} ends '# VERDICT: FAIL'") for ln in lines), lines


def test_attack_a_verdict_shadowed_from_a_shared_subdir_never_counts(scen):
    """The coder plants a PASS named like the tester's verdict in a shared subdir: not a verdict,
    in every pin; the tester's FAIL decides (237521d refused it too, as an AUTHORSHIP taint)."""
    s = built(scen, "FAIL")
    s.write("evidence/TEST-verdict-c9.md", "all good\n# VERDICT: PASS\n")
    scoped(s, R)
    scoped(s, A)
    s.done()
    manifests(s, coder=["evidence/TEST-verdict-c9.md"])
    code, lines = lines_of(s)
    assert code == 3 and any(ln.startswith(f"{T} ends '# VERDICT: FAIL'") for ln in lines), lines


def test_attack_evidence_planted_in_a_verifiers_private_dir_taints_red(scen):
    """The coder (on a harness without konstant's jail) plants a test in the tester's dir BEFORE
    the tester runs, so the tester's own pin covers it. Red on 237521d: MET."""
    s = scen(mode="runner")
    s.deliverable()
    s.write("verify-test/test_extra.py", "def test_extra():\n    assert True\n")
    scoped(s, T)
    scoped(s, R)
    scoped(s, A)
    s.done()
    manifests(s, coder=["verify-test/test_extra.py"])
    code, lines = lines_of(s)
    assert code == 3 and any(ln.startswith("AUTHORSHIP: verify-test/test_extra.py lies in the "
                                           f"private dir of {T}") and "2-coder" in ln
                             for ln in lines), lines


def test_twin_a_parallel_group_credits_each_private_dir_to_its_owner(scen):
    s = scen(mode="runner")
    s.deliverable()
    s.write("verify-test/run.log", "1 passed\n")
    s.write("verify-review/notes.md", "reviewed\n")
    scoped(s, T)
    scoped(s, R)
    scoped(s, A)
    s.done()
    manifests(s, tester=["verify-test/run.log"], reviewer=["verify-review/notes.md"])
    code, lines = lines_of(s)
    assert code == 0, lines


def test_twin_the_close_out_writing_a_private_dir_taints(scen):
    s = built(scen)
    scoped(s, A)
    s.write("verify-arch/fixed.md", "the close-out's note\n")
    s.done()
    manifests(s)
    s.manifest("05-0-orchestrator-c1", 0, "orchestrator", created=["DONE.md",
                                                                   "verify-arch/fixed.md"],
               closeout=True)
    code, lines = lines_of(s)
    assert code == 3 and any("AUTHORSHIP: verify-arch/fixed.md" in ln for ln in lines), lines


def test_attack_runner_unjailed_tamper_of_a_private_dir_taints_red(hws):  # noqa: F811
    """REVIEW L5-R2 5a's tamper on a harness without the jail: the closing architect drops a file
    into the tester's dir. Before L5-L2 only the tester's stale pin caught it (a re-run); now the
    manifests name it and the run is tainted."""
    env = hws.henv(FAKE_HARNESS_MODE="arch-tamper", KONSTANT_NO_JAIL="1")
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet(name)", "--project", "greeter", "--harness",
                          FAKE], capture_output=True, text=True, env=env, timeout=900,
                         cwd=str(hws.home))
    assert res.returncode != 0
    assert "AUTHORSHIP: verify-test/planted.md lies in the private dir of TEST-verdict.md" in \
        res.stderr, res.stderr[-3000:]
