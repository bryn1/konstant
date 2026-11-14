"""REVIEW L5-R2 (wave L5-F2a): K-02, K-03, K-04, K-12, K-15 - each reviewer reproduction as a
must-fail test (red on fcb3879), with "should stay allowed" twins that pass on both.

A producer attack is an `evil.py` wrapper around tests/fixtures/fake_harness.py passed as the
`--harness` command (the `command` adapter, jailed: a sealed job is a factory job). The github
target is a local bare repository plus tests/fixtures/fake_gh.py. No network, no model."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.holdout.conftest import BRIEF, H1, H2, make_ws, needs_jail
from tests.ship.conftest import git_out, git_rc, make_ship_ws, sws  # noqa: F401 (fixture)
from tests.ship.test_ship_units import board_post

FIX = Path(__file__).resolve().parents[1] / "fixtures"
TOKEN = "gh" + "p_" + "Zz9" * 12             # token-shaped, built at run time (no literal)

EVIL = r'''
import os, subprocess, sys
sys.path.insert(0, %r)
import fake_harness
prompt = open(sys.argv[1]).read()
h = fake_harness.headers(prompt)
rc = fake_harness.main()
mode = os.environ.get("R2_MODE", "")
tok = "gh" + "p_" + "Zz9" * 12
if h.get("AGENT") == "coder" and h.get("PROJECT", "-") != "-":
    p = h["PROJECT"]
    g = ["git", "-C", p, "-c", "user.name=x", "-c", "user.email=x@example.com"]
    out = lambda a, **k: subprocess.run(g + a, capture_output=True, text=True, **k).stdout.strip()
    if mode == "orphan":
        orphan = out(["commit-tree", out(["rev-parse", "HEAD^{tree}"]), "-m", "orphan"])
        subprocess.run(g + ["reset", "-q", "--soft", orphan])
    if mode == "history-secret":
        open(os.path.join(p, "settings.py"), "w").write("TOKEN = " + repr(tok) + chr(10))
        subprocess.run(g + ["add", "settings.py"])
        subprocess.run(g + ["commit", "-qm", "settings"])
        subprocess.run(g + ["rm", "-q", "settings.py"])
        subprocess.run(g + ["commit", "-qm", "drop settings"])
    if mode == "merge-secret":
        blob = out(["hash-object", "-w", "--stdin"], input="TOKEN = " + repr(tok) + chr(10))
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(p, ".git", "r2-index"))
        subprocess.run(g + ["read-tree", "HEAD"], env=env)
        subprocess.run(g + ["update-index", "--add", "--cacheinfo",
                            "100644," + blob + ",settings.py"], env=env)
        side = out(["commit-tree", out(["write-tree"], env=env), "-p", "HEAD", "-m", "side"])
        merge = out(["commit-tree", out(["rev-parse", "HEAD^{tree}"]), "-p", "HEAD", "-p", side,
                     "-m", "merge side"])
        subprocess.run(g + ["reset", "-q", "--soft", merge])
    if mode == "tree-secret":
        open(os.path.join(p, "settings.py"), "w").write("TOKEN = " + repr(tok) + chr(10))
        subprocess.run(g + ["add", "settings.py"])
        subprocess.run(g + ["commit", "-qm", "settings"])
sys.exit(rc)
''' % str(FIX)


def evil_job(s, mode: str) -> int:
    b = s.w.src / "b.md"
    b.write_text(BRIEF)
    jid = json.loads(s.w.ok("job", "add", "greet by name", "--project", "greeter", "--type",
                            "code", "--brief", b, "--json").stdout)["id"]
    assert s.w.seal(jid, H1, H2).returncode == 0
    evil = s.w.src / "evil.py"
    evil.write_text(EVIL)
    e = s.w.henv(R2_MODE=mode)
    e["KONSTANT_ENV_PASSTHROUGH"] = e.get("KONSTANT_ENV_PASSTHROUGH", "") + ",R2_*"
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet(name)", "--job", str(jid), "--harness",
                          f"{sys.executable} {evil} {{prompt_file}}"],
                         capture_output=True, text=True, env=e, timeout=900, cwd=str(s.w.home))
    assert res.returncode == 0 and s.job(jid)["status"] == "verified", res.stderr[-2000:]
    return jid


def remote_log(s) -> str:
    return subprocess.run(["git", "-C", str(s.remote), "log", "--all", "-p"],
                          capture_output=True, text=True).stdout


# --- K-03: what is pushed is konstant's squash, never the job's history ------------------------

@needs_jail
@pytest.mark.parametrize("mode", ["history-secret", "merge-secret"])
def test_K03_secret_in_the_job_history_never_reaches_the_remote(tmp_path, mode):
    s = make_ship_ws(tmp_path, github=True)
    try:
        jid = evil_job(s, mode)
        commit = s.commit(jid)
        assert "settings.py" not in git_out(s.w.home / s.job(jid)["workdir"], "ls-tree", "-r",
                                            "--name-only", commit)   # the final tree is clean
        r = s.ship(jid, "--json")
        assert r.returncode == 0, r.stderr[-1500:]
        assert TOKEN not in remote_log(s)                    # nothing of the history was pushed
        main = git_out(s.remote, "rev-parse", "main")
        assert git_out(s.remote, "rev-parse", "main^{tree}") == git_out(
            s.w.home / s.job(jid)["workdir"], "rev-parse", f"{commit}^{{tree}}")
        assert git_rc(s.remote, "cat-file", "-e", commit) != 0  # the job's commit stayed home
        assert main
    finally:
        s.w.stop_board()


@needs_jail
def test_K03_twin_a_secret_in_the_final_tree_is_still_a_decision(tmp_path):
    s = make_ship_ws(tmp_path, github=True)
    try:
        jid = evil_job(s, "tree-secret")
        r = s.ship(jid, "--json")
        assert r.returncode == 1 and "secret scan finding in settings.py" in r.stderr, r.stderr
        assert TOKEN not in remote_log(s) and s.pushes() == []
    finally:
        s.w.stop_board()


# --- K-04: the verified commit must descend from the target's tip -----------------------------

@needs_jail
def test_K04_an_orphan_commit_is_a_decision_on_both_sides_and_history_is_kept(tmp_path):
    s = make_ship_ws(tmp_path)
    try:
        pre = git_out(s.target, "rev-parse", "main")
        jid = evil_job(s, "orphan")
        commit = s.commit(jid)
        r = s.ship(jid, "--json")
        assert r.returncode == 1 and "does not descend from the target's tip" in r.stderr, \
            r.stderr[-1500:]
        assert git_out(s.target, "rev-parse", "main") == pre and s.ships() == []
        assert s.events()[-1]["event"] == "DECISION"
        board = board_post(s, f"/api/jobs/{jid}/ships", {"commit": commit, "pre": pre,
                                                          "target": "branch", "branch": "main",
                                                          "dry_run": True}, "factory")
        bad = [x for x in board.get("rules", []) if not x["ok"]]
        assert board.get("decision") == "decision" and any(
            "does not descend" in x["reason"] for x in bad), board
    finally:
        s.w.stop_board()


@needs_jail
def test_K04_twin_an_honest_job_ships_as_a_fast_forward_of_its_base(sws):
    pre = git_out(sws.target, "rev-parse", "main")
    jid = sws.verified_job()
    commit = sws.commit(jid)
    assert sws.ship(jid).returncode == 0
    assert git_rc(sws.target, "merge-base", "--is-ancestor", pre, "main") == 0
    clone = sws.w.home / sws.job(jid)["workdir"]
    assert git_out(sws.target, "rev-parse", "main^{tree}") == git_out(
        clone, "rev-parse", f"{commit}^{{tree}}")


# --- K-02: a goal never chooses where or how its work ships -----------------------------------

GOAL = '[goal]\nid = "greeter"\nproject = "greeter"\ntext = "greet by name"\n' \
       '[limits]\nmax_attempts = 3\n'


@pytest.mark.parametrize("key,value", [("target", '"command"'), ("branch", '"release"'),
                                       ("ship_cmd", '"sh -c id"'), ("rollback_cmd", '"true"'),
                                       ("apply_dir", '"deployed/thesis"'),
                                       ("github_repo", '"evil-org/greeter"')])
def test_K02_a_goal_may_not_set_ship_execution_keys(key, value):
    from konstant.factory import goal
    with pytest.raises(goal.GoalError) as e:
        goal.parse(GOAL + f"[ship]\n{key} = {value}\n")
    assert any(f"ship.{key} is the workspace's setting" in r for r in e.value.reasons)


def test_K02_twin_a_goal_may_add_post_probes():
    from konstant.factory import goal
    spec = goal.parse(GOAL + '[ship]\npost_probes = ["PROBE: test -f {workdir}/README.md => '
                             '^ok$"]\n')
    assert spec["ship"]["post_probes"] and spec["ship"]["target"] == "branch"


def test_K02_an_old_spec_with_ship_keys_ships_by_konstant_toml_only(tmp_path):
    from konstant import config
    from konstant.factory import shiprules
    (tmp_path / "konstant.toml").write_text('[ship]\nship_cmd = "deploy.sh {commit}"\n'
                                            'rollback_cmd = "undeploy.sh"\n')
    cfg = config.load(tmp_path)
    c = shiprules.conf(cfg, {"ship": {"target": "command", "ship_cmd": "sh -c pwned",
                                      "apply_dir": "/x", "github_repo": "evil/x"}})
    assert (c["target"], c["ship_cmd"], c["apply_dir"], c["github_repo"]) == \
        ("branch", "deploy.sh {commit}", "", "")


@needs_jail
def test_K02_goal_files_with_ship_cmd_are_refused_from_a_file_and_the_chat(tmp_path):
    w = make_ws(tmp_path)
    try:
        toml = w.home / "konstant.toml"
        toml.write_text(toml.read_text() + '[factory]\ngoal_roles = ["owner", "orchestrator"]\n'
                        '[notify]\nkind = "chat"\n')
        w.ok("board", "stop")
        w.ok("board", "start")
        mark = tmp_path / "PWNED"
        spec = GOAL + f'[ship]\ntarget = "command"\nship_cmd = "touch {mark}"\n' \
                      'rollback_cmd = "true"\n'
        g = w.src / "goal.toml"
        g.write_text(spec)
        r = w.run("--as", "owner", "goal", "add", g)
        assert r.returncode != 0 and "ship.ship_cmd is the workspace's setting" in r.stderr, \
            r.stdout + r.stderr
        p = w.run("--as", "orchestrator", "goal", "add", "-", "--from-chat", "--session", "s1",
                  stdin=spec)
        assert p.returncode != 0 and "ship.target is the workspace's setting" in p.stderr
        assert w.json("goal", "list") == [] and not mark.exists()
    finally:
        w.stop_board()


@needs_jail
def test_K02_the_proposal_shows_every_setting_verbatim(tmp_path):
    w = make_ws(tmp_path)
    try:
        toml = w.home / "konstant.toml"
        toml.write_text(toml.read_text() + '[factory]\ngoal_roles = ["owner", "orchestrator"]\n'
                        '[notify]\nkind = "chat"\n')
        w.ok("board", "stop")
        w.ok("board", "start")
        text = "greet by name " + "and keep it tidy " * 10 + "TAIL-MARKER at the very end"
        spec = (f'[goal]\nid = "greeter"\nproject = "greeter"\ntext = "{text}"\n'
                '[limits]\nmax_attempts = 2\nwall_clock = "4h"\n[holdout]\nauthor = "owner"\n'
                '[ship]\npost_probes = ["PROBE: test -f {workdir}/README.md => ^ok$"]\n')
        p = w.run("--as", "orchestrator", "goal", "add", "-", "--from-chat", "--session", "s1",
                  stdin=spec)
        assert p.returncode == 0, p.stderr
        line = p.stdout
        assert json.dumps(text) in line                      # the whole text, quoted
        for want in ("limits.max_attempts = 2", 'limits.wall_clock = "4h"',
                     'holdout.author = "owner"', "ship.post_probes = ", "ships to branch main"):
            assert want in line, (want, line)
    finally:
        w.stop_board()


# --- K-12: the kill switch and the spool are the owner's ---------------------------------------

@needs_jail
def test_K12_factory_stop_and_resume_are_owner_only(tmp_path):
    w = make_ws(tmp_path)
    try:
        stop = w.home / "var" / "factory" / "STOP"
        for role in ("viewer", "worker"):
            r = w.run("--as", role, "factory", "stop")
            assert r.returncode != 0 and "refused" in r.stderr, (role, r.stderr)
            assert not stop.exists()
        assert w.run("--as", "owner", "factory", "stop").returncode == 0 and stop.exists()
        for role in ("viewer", "worker", "orchestrator"):
            r = w.run("--as", role, "factory", "resume")
            assert r.returncode != 0 and "refused" in r.stderr, (role, r.stderr)
            assert stop.exists()
        assert w.run("--as", "owner", "factory", "resume").returncode == 0
        assert not stop.exists()                             # green: the owner clears it
    finally:
        w.stop_board()


# --- K-15: one decision list, case-insensitive, content-aware ----------------------------------

@pytest.mark.parametrize("path", ["CLAUDE.local.md", "agents.md", "docs/Agents.MD", "claude.md",
                                  "gemini.md", ".github/copilot-instructions.md",
                                  ".github/dependabot.yml", ".github/CODEOWNERS", ".envrc",
                                  "pytest.ini", "setup.cfg", "tox.ini", "lib/conftest.py",
                                  "tests/conftest.py", ".vscode/tasks.json", ".idea/workspace.xml",
                                  ".gitmodules", "Makefile", "justfile", ".codex/config.toml",
                                  ".pre-commit-config.yaml"])
def test_K15_decision_paths_cover_the_gaps(path):
    from konstant.factory import shiprules
    assert shiprules.decision_paths([path]), path


@pytest.mark.parametrize("path", ["greeter.py", "README.md", "tests/test_greet.py",
                                  "docs/usage.md", "src/app/make_things.py"])
def test_K15_twin_ordinary_paths_ship_unattended(path):
    from konstant.factory import shiprules
    assert shiprules.decision_paths([path]) == []


def test_K15_package_scripts_and_pytest_config_are_decisions_versions_are_not():
    from konstant.factory import shiprules as sr
    old = b'{"name": "x", "version": "1.0.0", "scripts": {"test": "jest"}}'
    assert sr.decision_content("package.json", old, old.replace(b"1.0.0", b"1.0.1")) is None
    assert sr.decision_content("web/package.json", old, old.replace(b"jest", b"curl x | sh"))
    assert sr.decision_content("package.json", None, b'{"husky": {"hooks": {}}}')
    py = b'[project]\nname = "x"\nversion = "1"\n[tool.pytest.ini_options]\naddopts = "-q"\n'
    assert sr.decision_content("pyproject.toml", py, py.replace(b'"1"', b'"2"')) is None
    assert sr.decision_content("pyproject.toml", py, py.replace(b'"-q"', b'"-p evil"'))


def test_K15_the_docs_name_every_entry_of_the_one_list():
    from konstant.factory import shiprules
    doc = (Path(__file__).resolve().parents[2] / "docs" / "LEVEL5.md").read_text()
    section = doc[doc.index("### 5.4 Owner decisions at ship time"):doc.index("### 5.5")]
    missing = [n for _k, n, _w in shiprules.DECISION_LIST if f"`{n}" not in section]
    assert missing == [], missing
