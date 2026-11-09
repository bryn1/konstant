"""Unit and board-route tests of the ship guard (docs/LEVEL5.md 5.2, 5.4; wave L5-4): each rule
red beside green, the ship repository's re-hash, the ships table's triggers and the route roles."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import urllib.error
import urllib.request
import zlib
from pathlib import Path

import pytest

from konstant.factory import shiprepo, shiprules


def board_post(s, route: str, body: dict, label: str = "factory") -> dict:
    """POST to the test board with one identity's token; the JSON answer (or {"status": code})."""
    from konstant import config
    cfg = config.load(s.w.home)
    tok = (cfg.secrets_dir / f"{label}.token").read_text().strip()
    req = urllib.request.Request(cfg.base_url + route, data=json.dumps(body).encode(),
                                 method="POST", headers={"Authorization": f"Bearer {tok}",
                                                         "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "detail": json.loads(exc.read()).get("detail")}


# --- decision paths (5.4) --------------------------------------------------------------------

@pytest.mark.parametrize("path", ["AGENTS.md", "sub/CLAUDE.md", ".claude/settings.json",
                                  "x/.dsh/a.yml", ".gemini/s.json", ".agents/skills/a.md",
                                  ".github/workflows/ci.yml", "sitecustomize.py",
                                  "lib/usercustomize.py", "evil.pth", "conftest.py",
                                  "src/conftest.py", "GEMINI.md"])
def test_decision_paths_red(path):
    assert shiprules.decision_paths([path]), path


@pytest.mark.parametrize("path", ["greeter.py", "README.md", "tests/conftest.py",
                                  "test/conftest.py", "docs/agents.md", ".github/CODEOWNERS",
                                  "src/pathlib_extra.py"])
def test_decision_paths_green(path):
    assert shiprules.decision_paths([path]) == [], path


# --- the holdout rules over board records (5.2 rules 1-3) ------------------------------------

def _set(commit="c" * 40):
    sealed = [{"hid": "H1", "sha256": "a" * 64, "kind": "proof"},
              {"hid": "H2", "sha256": "b" * 64, "kind": "regression"}]
    from konstant.verify.holdout import digest
    rows = [{"hid": h["hid"], "passed": True, "commit": commit} for h in sealed]
    ver = {"verdict": "PASS", "holdouts": {"rows": rows, "commit": commit, "digest": digest(sealed),
                                           "leak": False}}
    job = {"id": 2, "status": "verified", "evidence": {"commit": commit}}
    return job, ver, sealed


def _ok(rules):
    return all(r[1] for r in rules)


def test_verified_rules_green():
    job, ver, sealed = _set()
    assert _ok(shiprules.verified_rules(job, ver, sealed, 2, "c" * 40))


@pytest.mark.parametrize("planted", ["status", "verdict", "leak", "failed", "digest", "count",
                                     "evidence", "ship", "row-commit", "no-holdouts"])
def test_verified_rules_red(planted):
    job, ver, sealed = _set()
    h, commit = ver["holdouts"], "c" * 40
    if planted == "status":
        job["status"] = "completed_unverified"
    elif planted == "verdict":
        ver["verdict"] = "FAIL"
    elif planted == "leak":
        h["leak"] = True
    elif planted == "failed":
        h["rows"][1]["passed"] = False
    elif planted == "digest":
        h["digest"] = "0" * 64
    elif planted == "count":
        h["rows"] = h["rows"][:1]
    elif planted == "evidence":
        job["evidence"]["commit"] = "d" * 40
    elif planted == "ship":
        commit = "e" * 40
    elif planted == "row-commit":
        h["rows"][0]["commit"] = "f" * 40
    elif planted == "no-holdouts":
        ver["holdouts"], sealed = None, []
    assert not _ok(shiprules.verified_rules(job, ver, sealed, 2, commit)), planted


def test_regression_only_red_and_green():
    assert shiprules.regression_only([{"kind": "regression"}, {"kind": "regression"}])
    assert not shiprules.regression_only([{"kind": "proof"}, {"kind": "regression"}])


# --- the ship repository: content-addressed import --------------------------------------------

def _repo(tmp: Path, name: str) -> Path:
    r = tmp / name
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    (r / "a.py").write_text("print('a')\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True, env=env)
    return r


def _commit(repo: Path, name: str, text: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    (repo / name).write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", name], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", name], check=True, env=env)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


class _Cfg:
    def __init__(self, home):
        self.home = Path(home)


def test_import_copies_the_real_objects_green(tmp_path):
    target = _repo(tmp_path, "target")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--shared", str(target), str(clone)], check=True)
    c = _commit(clone, "b.py", "print('b')\n")
    repo = shiprepo.ensure(_Cfg(tmp_path), "t", target)
    assert shiprepo.import_from_clone(_Cfg(tmp_path), repo, clone, c) >= 3
    assert shiprepo.out(repo, "cat-file", "-t", c) == "commit"
    assert shiprepo.out(repo, "cat-file", "blob", f"{c}:b.py") == "print('b')"


def test_import_refuses_an_object_whose_content_is_not_its_id_red(tmp_path):
    target = _repo(tmp_path, "target")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--shared", str(target), str(clone)], check=True)
    c = _commit(clone, "b.py", "print('b')\n")
    blob = subprocess.run(["git", "-C", str(clone), "rev-parse", f"{c}:b.py"],
                          capture_output=True, text=True).stdout.strip()
    p = clone / ".git" / "objects" / blob[:2] / blob[2:]
    os.chmod(p, 0o644)
    p.write_bytes(zlib.compress(b"blob 9\0BROKEN!!\n"))
    repo = shiprepo.ensure(_Cfg(tmp_path), "t", target)
    with pytest.raises(shiprepo.ShipRepoError, match="does not hash to its id"):
        shiprepo.import_from_clone(_Cfg(tmp_path), repo, clone, c)


def test_secret_scan_names_the_path_not_the_text(tmp_path):
    target = _repo(tmp_path, "target")
    pre = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True,
                         text=True).stdout.strip()
    shape = "gh" + "p_" + "Q7" * 18                        # token-shaped, built at run time
    c = _commit(target, "conf.py", f"TOKEN = '{shape}'\n")
    from konstant.release import scan
    pats = scan.load_patterns(Path(__file__).resolve().parents[2] / "release" / "patterns.toml")
    found = shiprules.secret_findings(target, pre, c, pats)
    assert found and all(f.startswith("conf.py (") for f in found) and shape not in "".join(found)
    c2 = _commit(target, "ok.py", "print('nothing secret')\n")
    assert shiprules.secret_findings(target, c, c2, pats) == []


# --- the ships table (append-only state) -------------------------------------------------------

def test_ships_triggers_refuse_going_back_and_rewriting(tmp_path):
    from konstant.board import migrate
    db = tmp_path / "b.db"
    migrate.migrate(db)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO projects (slug, name, path) VALUES ('p', 'p', 'p')")
    con.execute("INSERT INTO jobs (project_id, type, title, brief, acceptance, status, "
                "requested_by) VALUES (1, 'project', 'p', '', '', 'queued', 'o')")
    con.execute("INSERT INTO ships (job_id, target, commit_sha, pre_ref, state, actor) VALUES "
                "(1, 'branch', ?, ?, 'shipping', 'factory')", ("a" * 40, "b" * 40))
    with pytest.raises(sqlite3.IntegrityError):              # one ship at a time
        con.execute("INSERT INTO ships (job_id, target, commit_sha, pre_ref, state, actor) "
                    "VALUES (1, 'branch', ?, ?, 'shipping', 'factory')", ("c" * 40, "b" * 40))
    con.execute("UPDATE ships SET state='shipped', tip_sha=? WHERE id=1", ("a" * 40,))
    for bad in ("UPDATE ships SET state='shipping' WHERE id=1",
                "UPDATE ships SET commit_sha='" + "d" * 40 + "' WHERE id=1",
                "UPDATE ships SET tip_sha='" + "e" * 40 + "' WHERE id=1",
                "DELETE FROM ships WHERE id=1"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(bad)
    con.execute("UPDATE ships SET state='rolled_back', rollback_sha=? WHERE id=1", ("f" * 40,))
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE ships SET state='shipped' WHERE id=1")
    con.execute("INSERT INTO shipping_log (state, reason, actor) VALUES ('halted', 'x', 'f')")
    for bad in ("UPDATE shipping_log SET state='resumed'", "DELETE FROM shipping_log"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(bad)


# --- route roles (the board side of the guard) -------------------------------------------------

@pytest.fixture()
def bws(tmp_path):
    from tests.ship.conftest import make_ship_ws
    s = make_ship_ws(tmp_path)
    yield s
    s.w.stop_board()


def test_only_the_factory_identity_ships_red_and_green(bws):
    body = {"commit": "a" * 40, "pre": "b" * 40, "target": "branch", "branch": "main",
            "dry_run": True}
    for label in ("owner", "orchestrator", "worker", "verifier", "planner", "scenario"):
        out = board_post(bws, "/api/jobs/1/ships", body, label)
        assert out.get("status") == 403, (label, out)
    out = board_post(bws, "/api/jobs/1/ships", body, "factory")        # green: it may ask
    assert out.get("decision") == "refused" and "ship" not in out


def test_shipping_halt_and_resume_roles(bws):
    assert board_post(bws, "/api/factory/shipping", {"action": "halt"}, "worker")["status"] == 403
    assert board_post(bws, "/api/factory/shipping", {"action": "halt"}, "factory") == \
        {"shipping": "halted"}
    for label in ("factory", "orchestrator", "verifier"):
        out = board_post(bws, "/api/factory/shipping", {"action": "resume"}, label)
        assert out["status"] == 403, label
    assert board_post(bws, "/api/factory/shipping", {"action": "resume"}, "owner") == \
        {"shipping": "open"}


def test_ship_decision_is_the_owners_alone(bws):
    for label in ("factory", "orchestrator", "worker"):
        out = board_post(bws, "/api/jobs/1/ship-decision", {"commit": "a" * 40}, label)
        assert out["status"] == 403, label
    out = board_post(bws, "/api/jobs/1/ship-decision", {"commit": "a" * 40}, "owner")
    assert out["status"] == 409                     # green role, but job 1 is not verified


def test_ship_and_factory_verbs_are_refused_inside_a_task_run_and_the_chat(bws):
    for env in ({"KONSTANT_IN_TASK": "1"}, {"KONSTANT_CHAT_SESSION": "s1"}):
        r = bws.w.run("ship", "1", "--dry-run", env=bws.w.env(**env))
        assert r.returncode == 1 and "refused" in r.stderr, r.stderr
        r = bws.w.run("--as", "owner", "factory", "resume-shipping", env=bws.w.env(**env))
        assert r.returncode == 1 and "refused" in r.stderr
    assert bws.w.run("ship", "list").returncode == 0                       # green: a read


def test_conf_resolution_goal_over_workspace(tmp_path):
    from konstant import config
    (tmp_path / "konstant.toml").write_text('[ship]\ngithub_repo = "ws-org/ws"\n'
                                            'remote = "/x/remote.git"\n')
    cfg = config.load(tmp_path)
    c = shiprules.conf(cfg, None)
    assert c["target"] == "branch" and c["branch"] == "main" and c["remote"] == "/x/remote.git"
    spec = {"ship": {"target": "github", "branch": "trunk", "post_probes": ["PROBE: a => ^b$"],
                     "github_repo": "goal-org/g"}}
    c = shiprules.conf(cfg, spec)
    assert (c["target"], c["branch"], c["github_repo"]) == ("github", "trunk", "goal-org/g")
    assert c["remote"] == "/x/remote.git" and c["post_probes"] == ["PROBE: a => ^b$"]
    (tmp_path / "konstant.toml").write_text('[ship]\ngh = "gh"\n')
    with pytest.raises(config.ConfigError, match="absolute path"):
        config.load(tmp_path)


def test_ship_git_env_inherits_no_git_variable_red_then_green(monkeypatch, tmp_path):
    """An inherited GIT_* variable (here an extra alternate object dir) never reaches the ship's
    git: the red twin shows git honours it when it is passed through."""
    target = _repo(tmp_path, "target")
    other = _repo(tmp_path, "other")
    oid = _commit(other, "o.py", "print('other')\n")
    alt = str(other / ".git" / "objects")
    red = subprocess.run(["git", "-C", str(target), "cat-file", "-t", oid], capture_output=True,
                         text=True, env={**os.environ, "GIT_ALTERNATE_OBJECT_DIRECTORIES": alt})
    assert red.stdout.strip() == "commit"                     # the variable does change a read
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", alt)
    assert "GIT_ALTERNATE_OBJECT_DIRECTORIES" not in shiprepo.git_env()
    assert shiprepo.missing(target, [oid]) == [oid]           # green: the ship's git ignores it


def test_a_ship_branch_the_target_lacks_is_named_not_called_moved(tmp_path):
    from konstant.factory import localtarget
    target = _repo(tmp_path, "target")
    pre = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True,
                         text=True).stdout.strip()
    rules = localtarget.local_checks(target, "refs/heads/trunk", pre, [])
    assert rules[0][:2] == ("target", False) and "has no branch trunk" in rules[0][2]
    assert "checked-out branch is main" in rules[0][2]
    assert localtarget.local_checks(target, "refs/heads/main", pre, [])[0][1] is True
