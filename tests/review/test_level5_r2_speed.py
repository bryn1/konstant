"""REVIEW L5-R2 (wave L5-F2b): speed (item 5a/5c) and K-11, K-14, K-17, K-18 - each as a must-fail
test (red on 53ac137), with "should stay refused" twins for the attacks a narrower pin must still
stop.

5a: a verifying phase's evidence in its own OUT/verify-<stem>/ no longer stales the other
    verdicts; a producer or a later phase that alters what a verdict judged still does (and the
    jail refuses the write outright);
5c: per-phase timeouts ([gate] phase_timeout_s), tester and reviewer 7200 s by default;
K-11: the held-out lint reads the goal text; K-14: a github rollback reverts only the ship
commit's change; K-17: a follow-up chain is capped and every rollback is an escalation;
K-18: a seal cut off before its rename is recovered or discarded."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.gate.conftest import done_text
from tests.holdout.conftest import BRIEF, H1, H2, needs_jail
from tests.ship.conftest import git_out, make_ship_ws

FAKE = f"{sys.executable} {os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'fake_harness.py')} {{prompt_file}}"


def judge(s, scope: str = "") -> str:
    from konstant.gate.rules import judged
    return judged.judge(s.rec, scope)


def scoped_verdict(s, name: str, word: str = "PASS"):
    return s.write(name, f"findings: checked\n# JUDGED: {judge(s, name)}\n# VERDICT: {word}\n")


def judged_findings(s) -> list:
    return [f.text for f in s.check()[3] if f.rule == "judged"]


# --- 5a: scoped pins (rule level) -------------------------------------------------------------

def test_5a_evidence_in_a_verifiers_own_dir_does_not_stale_the_others(scen):
    s = scen()
    s.deliverable()
    scoped_verdict(s, "TEST-verdict.md")
    scoped_verdict(s, "REVIEW-verdict.md")
    s.write("verify-arch/notes.md", "the architect's second pass, written after both pins\n")
    scoped_verdict(s, "ARCH-verdict.md")
    s.done()
    assert judged_findings(s) == []
    code, lines, _w, _f = s.check()
    assert code == 0, lines


@pytest.mark.parametrize("where", ["out", "project", "owner-dir"])
def test_5a_attack_a_later_change_to_what_was_judged_still_stales_it(scen, where):
    s = scen()
    s.deliverable()
    scoped_verdict(s, "TEST-verdict.md")
    s.write("verify-test/run.log", "1 passed\n")      # the tester's own evidence ...
    scoped_verdict(s, "TEST-verdict.md")              # ... pinned with it
    scoped_verdict(s, "REVIEW-verdict.md")
    if where == "out":                                # the producer's test, weakened later
        s.write("test_greet.py", "def test_greet():\n    assert True\n")
    elif where == "project":
        s.write("greet.py", 'def greet():\n    return "hi"\n', s.project)
    else:                                             # another phase rewrites the tester's log
        s.write("verify-test/run.log", "0 failed\n")
    scoped_verdict(s, "ARCH-verdict.md")
    s.done()
    found = judged_findings(s)
    assert any(t.startswith("TEST-verdict.md judged a different deliverable state")
               for t in found), found


def test_5a_attack_a_pin_of_another_scope_is_refused(scen):
    s = scen()
    s.deliverable()
    s.write("REVIEW-verdict.md", f"ok\n# JUDGED: {judge(s, 'TEST-verdict.md')}\n# VERDICT: PASS\n")
    found = judged_findings(s)
    assert any("PIN-SCOPE-DIFFERS" in t and "REVIEW-verdict.md" in t for t in found), found


def test_5a_attack_evidence_no_verdict_covers_is_unmet(scen):
    s = scen(ttype="security")          # its closing architect runs only when the project changed
    s.write("FINDINGS-security.md", "nothing found\n")
    s.write("verify-arch/claims.md", "the architecture holds\n")
    scoped_verdict(s, "REVIEW-verdict.md")
    s.done(done_text())
    found = judged_findings(s)
    assert any(t.startswith("UNPINNED:") and "verify-arch" in t for t in found), found


def test_5a_twin_a_full_pin_still_covers_everything(scen):
    s = scen()
    s.deliverable()
    s.verdict("TEST-verdict.md")                      # no --for: the whole state, as before
    s.write("verify-arch/notes.md", "later evidence\n")
    assert any(t.startswith("TEST-verdict.md judged a different") for t in judged_findings(s))


# --- 5a: the runner and the jail --------------------------------------------------------------

def _phase_runs(rd, agent: str) -> int:
    return sum(1 for p in (rd / "phases").glob("*.json")
               if json.loads(p.read_text()).get("agent") == agent)


@needs_jail
def test_5a_runner_verifier_evidence_costs_no_re_judge(hws):  # noqa: F811
    res, rd = hws.task_run("evidence", job=hws.add_job())
    assert res.returncode == 0, res.stderr[-3000:]
    assert "resume" not in res.stderr, res.stderr[-3000:]
    assert _phase_runs(rd, "tester") == 1 and _phase_runs(rd, "reviewer") == 1


@needs_jail
def test_5a_jail_refuses_a_verifier_writing_what_it_judged(hws):  # noqa: F811
    res, rd = hws.task_run("arch-tamper", job=hws.add_job())
    rec = json.loads((rd / "record.json").read_text())
    out = rec["out"]
    log = open(os.path.join(out, "verify-arch", "tamper.log")).read()
    assert "refused test_greet.py" in log and "refused planted.md" in log, log
    assert "weakened" not in open(os.path.join(out, "test_greet.py")).read()
    assert res.returncode == 0, res.stderr[-3000:]


def test_5a_twin_unjailed_the_pin_still_catches_the_tamper(hws):  # noqa: F811
    """A level-4 phase without konstant's jail (the command harness, no factory state) is not
    stopped from writing, so the pin catches it (and since L5-L2 the manifests taint the run: a
    private dir is written only by its owner)."""
    env = hws.henv(FAKE_HARNESS_MODE="arch-tamper", KONSTANT_NO_JAIL="1")
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet(name)", "--project", "greeter", "--harness",
                          FAKE], capture_output=True, text=True, env=env, timeout=900,
                         cwd=str(hws.home))
    both = res.stdout + res.stderr      # L5-L2: the manifests now also taint it at once (STOP,
    assert "TEST-verdict.md judged a different deliverable state" in both, both[-3000:]  # stdout)


# --- 5c: per-phase timeouts -------------------------------------------------------------------

def test_5c_phase_timeouts_per_role_with_local_model_defaults(tmp_path):
    from konstant import catalog, config
    from konstant.gate.harness import HarnessSet
    (tmp_path / "konstant.toml").write_text('[harness]\nname = "command"\n'
                                            'command = "true {prompt_file}"\n')
    cfg = config.load(tmp_path)
    hs = HarnessSet(cfg.data["harness"], tmp_path, catalog.load())
    assert hs.phase_timeout("tester") == 7200 and hs.phase_timeout("reviewer") == 7200
    assert hs.phase_timeout("coder") == 3600
    (tmp_path / "konstant.toml").write_text('[harness]\nname = "command"\n'
                                            'command = "true {prompt_file}"\n'
                                            '[gate.phase_timeout_s]\ndefault = 5400\ncode = 900\n')
    hs = HarnessSet(config.load(tmp_path).data["harness"], tmp_path, catalog.load())
    assert hs.phase_timeout("coder", "code") == 900 and hs.phase_timeout("tester") == 7200
    assert hs.phase_timeout("writer", "docs") == 5400


def test_5c_a_phase_past_its_timeout_is_stopped(tmp_path):
    from konstant import catalog, config
    from konstant.gate.harness import HarnessSet
    (tmp_path / "konstant.toml").write_text('[harness]\nname = "command"\n'
                                            'command = "sh -c \'sleep 30\' {prompt_file}"\n[gate]\njail = '
                                            'false\n')
    hs = HarnessSet(config.load(tmp_path).data["harness"], tmp_path, catalog.load(), jail=False)
    r = hs.run("x", agent="coder", cwd=tmp_path, run_dir=tmp_path / "run", label="01-1-coder",
               timeout_s=1)
    assert r.rc == 124 and r.timed_out


# --- K-11 ---------------------------------------------------------------------------------------

GOAL = "greet by name, e.g. greet('Ada') prints hello Ada"


def test_K11_a_goal_example_is_not_held_out(tmp_path):
    from konstant.holdout import draft, lint, store
    sc = lint.parse(lint.with_canary(H1.encode()), "H1")
    assert not lint.lint(sc, BRIEF, BRIEF)                     # held out of the brief and DoD
    found = lint.lint(sc, BRIEF, BRIEF, goal=GOAL)
    assert any(r.startswith("NOT HELD OUT: H1") and "goal text" in r for r in found), found
    f = tmp_path / "a.scenario"
    f.write_text(H1)
    rows = draft.check([f], {"brief": BRIEF, "acceptance": BRIEF, "need": 1, "goal": GOAL})
    assert any("goal text" in r for r in rows["drafts"][0]["reasons"]), rows

    class C:
        def get(self, path):
            assert path == "/api/goals/7"
            return {"spec": {"goal": {"text": GOAL}}}
    assert store.goal_text(C(), {"goal_id": 7}) == GOAL        # what seal() lints against
    assert store.goal_text(C(), {"goal_id": None}) == ""


# --- K-14 ---------------------------------------------------------------------------------------

@needs_jail
def test_K14_a_github_rollback_keeps_a_commit_merged_meanwhile(tmp_path):
    from tests.fixtures import fake_gh
    s = make_ship_ws(tmp_path, github=True, tail='[notify]\nkind = "file"\n')
    try:
        spec = tmp_path / "intervene.json"
        spec.write_text(json.dumps({"path": "OTHER.md", "text": "someone else's work\n"}))
        fake_gh.install(tmp_path / "pinned", s.remote, s.gh_log, intervene=spec)
        s.w.ok("agents", "sync")                     # the re-written gh stand-in is pinned again
        jid = s.verified_job()
        pre = s.job(jid)["workdir_base"]
        r = s.ship(jid)
        assert r.returncode == 3, r.stderr + r.stdout[-1500:]      # merged tree != verified
        assert s.ships()[0]["state"] == "rolled_back"
        assert git_out(s.remote, "show", "main:OTHER.md") == "someone else's work"
        for path in ("greeter.py", "README.md"):
            assert git_out(s.remote, "show", f"main:{path}") == git_out(s.remote, "show",
                                                                       f"{pre}:{path}"), path
        assert any(e["event"] == "ROLLED_BACK" and e["kind"] == "escalation" for e in s.events())
    finally:
        s.w.stop_board()


def test_K14_a_conflicting_revert_is_refused_never_guessed(tmp_path):
    from konstant.factory import shiprepo, targets
    repo = tmp_path / "r.git"
    subprocess.run(["git", "init", "-q", "--bare", str(repo)], check=True)
    env = {**os.environ, "GIT_DIR": str(repo), "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}

    def commit(files: dict, parents: list) -> str:
        idx = str(tmp_path / "idx")
        e = {**env, "GIT_INDEX_FILE": idx}
        if os.path.exists(idx):
            os.unlink(idx)
        for name, text in files.items():
            blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=text,
                                  capture_output=True, text=True, env=e, check=True).stdout.strip()
            subprocess.run(["git", "update-index", "--add", "--cacheinfo",
                            f"100644,{blob},{name}"], env=e, check=True)
        tree = subprocess.run(["git", "write-tree"], capture_output=True, text=True, env=e,
                              check=True).stdout.strip()
        args = ["git", "commit-tree", tree, "-m", "c"] + sum((["-p", p] for p in parents), [])
        return subprocess.run(args, capture_output=True, text=True, env=env,
                              check=True).stdout.strip()

    pre = commit({"a.txt": "one\n"}, [])
    head = commit({"a.txt": "two\n"}, [pre])
    later = commit({"a.txt": "three\n"}, [head])           # someone changed the same path
    with pytest.raises(targets.RollbackConflict):
        targets.revert_commit(repo, pre, head, later, 1)
    other = commit({"a.txt": "two\n", "b.txt": "x\n"}, [head])     # a different path: fine
    rb = targets.revert_commit(repo, pre, head, other, 1)
    assert shiprepo.reverted(repo, pre, head, rb)
    assert git_out(repo, "show", f"{rb}:b.txt") == "x"


# --- K-17 ---------------------------------------------------------------------------------------

class _Client:
    def __init__(self, ships):
        self.ships, self.posts = ships, []

    def get(self, path, **kw):
        return {"ships": self.ships} if path == "/api/ships" else {}

    def post(self, path, body=None):
        self.posts.append(path)
        return {"id": 99, "new": True}


def test_K17_a_follow_up_chain_is_capped_whatever_max_rollbacks_says(tmp_path, monkeypatch):
    from konstant import config
    from konstant.factory import ship
    cfg = config.load(tmp_path)
    told = []
    monkeypatch.setattr(ship, "escalate", lambda cfg, client, plan, ev, why: told.append(ev))
    chain = [{"id": i, "job_id": 10 + i, "follow_up_id": 11 + i, "state": "rolled_back",
              "goal_id": 1} for i in range(3)]               # job 13 is 3 follow-ups deep
    c = _Client(chain)
    plan = {"goal": {"id": 1, "slug": "g", "spec": {"limits": {"max_rollbacks": 0}}},
            "job": {"id": 13, "display_id": "1.4"}}
    assert ship.follow_up(cfg, c, plan, 7, {"failed_probes": []}) is None
    assert told == ["BLOCKED"] and not [p for p in c.posts if p.endswith("/follow-up")]


def test_K17_every_rollback_is_an_escalation():
    from konstant.factory import notify
    assert "ROLLED_BACK" in notify.ESCALATIONS and "ROLLED_BACK" not in notify.OUTCOMES


# --- K-18 ---------------------------------------------------------------------------------------

@needs_jail
def test_K18_a_seal_cut_off_is_recovered_or_discarded(hws):  # noqa: F811
    from tests.ship.conftest import H3
    jid = hws.add_job()
    store = hws.home / "var" / "holdout" / str(jid)
    assert hws.seal(jid, H1, H2).returncode == 0
    os.replace(store / "H2.scenario", store / ".H2.staged")    # cut off before its rename
    stale = store / ".H3.staged"                               # cut off before the board post
    stale.write_text("SCENARIO: junk\n")
    os.chmod(stale, 0o400)
    r = hws.seal(jid, H3)
    assert r.returncode == 0, r.stderr
    assert (store / "H2.scenario").is_file() and not (store / ".H2.staged").exists()
    assert "recovered H2" in r.stderr and "discarded a staged H3" in r.stderr, r.stderr
    assert sorted(p.name for p in store.iterdir()) == ["H1.scenario", "H2.scenario",
                                                       "H3.scenario"]


# --- live finding of L5-F2b: git in a factory phase ------------------------------------------

def _repo(tmp_path):
    repo = tmp_path / "p"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    (repo / "a.txt").write_text("a\n")
    for args in (("add", "a.txt"), ("-c", "user.name=t", "-c", "user.email=t@example.com",
                                    "commit", "-qm", "a")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, env=env)
    return repo


def test_live_git_still_works_in_a_factory_phase_whose_harness_drops_key_names(tmp_path):
    """The live run's tester saw `missing config key GIT_CONFIG_KEY_0` on every git call: the
    credential reset of K-10 was a GIT_CONFIG_COUNT/KEY_0/VALUE_0 triple and a filter on the way
    into the phase's shell dropped the *KEY* name. The reset must survive such a filter whole."""
    from konstant import confinement
    repo = _repo(tmp_path)
    conf = confinement.parse({"profile": "closed"}, tmp_path).for_phase("worker", True)
    env = conf.withheld_env({**os.environ, "GIT_CONFIG_GLOBAL": os.devnull})
    shell = {k: v for k, v in env.items() if "KEY" not in k and "TOKEN" not in k}
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True, env=shell)
    assert r.returncode == 0, r.stderr
    h = subprocess.run(["git", "-C", str(repo), "config", "--get-all", "credential.helper"],
                       capture_output=True, text=True, env=shell)
    assert h.stdout.strip() == "", h.stdout                 # the reset is still in force


def test_live_konstants_own_git_view_ignores_an_inherited_git_config(tmp_path, monkeypatch):
    from konstant.gate.rules import common
    repo = _repo(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")             # a half-filtered triple
    assert common.git_top(repo) == str(repo)


def test_live_the_judge_refuses_a_git_project_it_cannot_read(tmp_path):
    from konstant.gate.rules import judged
    proj = tmp_path / "p"
    (proj / "out").mkdir(parents=True)
    (proj / "x.py").write_text("x = 1\n")
    rec = {"out": str(proj / "out"), "project": str(proj), "git_base": "a" * 40}
    with pytest.raises(judged.JudgeRefused, match="git cannot read"):
        judged.judge(rec)
