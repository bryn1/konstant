"""Job clones and the read-only target (docs/LEVEL5.md 2.4, wave L5-2): the first claim of a
holdout job records `projects/<slug>@<job>` and the target commit on the board; the runner makes
the clone with plumbing; the phases work there; the verifier judges the clone (re-run, holdouts,
`{workdir}` probes) and the target is untouched."""
from __future__ import annotations

import json
import pytest

from konstant.factory import clone
from tests.factory.conftest import git_out, run, sealed_job
from tests.holdout.conftest import BRIEF, git, needs_jail

WORKDIR_BRIEF = BRIEF.replace("PROBE: test -f projects/greeter/greeter.py => ^ok$",
                              "PROBE: grep -c greet(name {workdir}/greeter.py => ^1$")


@needs_jail
def test_honest_run_works_in_the_clone_and_leaves_the_target_untouched(fws):
    target = fws.home / "projects" / "greeter"
    tip = git_out(target, "rev-parse", "HEAD")
    before = (target / "greeter.py").read_text()
    jid = sealed_job(fws, WORKDIR_BRIEF)
    res, rd = run(fws, "command", jid)
    assert res.returncode == 0, res.stderr[-3000:]
    job = fws.json("job", "show", jid)
    assert job["workdir"] == f"projects/greeter@{jid}" and job["workdir_base"] == tip
    wd = fws.home / job["workdir"]
    rec = json.loads((rd / "record.json").read_text())
    assert rec["project"] == str(wd.resolve()) and rec["git_base"] == tip
    assert rec["out"].startswith(str(wd.resolve()) + "/.audits/")
    assert git_out(target, "rev-parse", "HEAD") == tip                     # target unchanged
    assert (target / "greeter.py").read_text() == before
    assert not (target / ".audits").exists()
    commit = job["evidence"]["commit"]
    assert git_out(wd, "rev-parse", "HEAD") == commit != tip              # the work: in the clone
    assert job["evidence"].get("base") == tip
    v = job["verifications"][-1]
    assert v["verdict"] == "PASS"
    from konstant.board import db
    from konstant.config import load
    with db.reading(load(fws.home).db_path) as conn:
        probes = json.loads(conn.execute("SELECT probes_json FROM verifications WHERE id=?",
                                         (v["id"],)).fetchone()[0])
    assert [p["line"] for p in probes] == [
        f"PROBE: grep -c greet(name projects/greeter@{jid}/greeter.py => ^1$"]
    assert probes[0]["matched"] is True and probes[0]["source"] == "dod"


@needs_jail
def test_workdir_probe_contradicts_when_the_clone_lacks_the_work(fws):
    """Red twin of the {workdir} substitution: the same probe against the TARGET (no greet(name)
    there) is a contradiction, so the PASS above was the clone's own result."""
    from konstant.config import load
    from konstant.verify import probe, verifier
    cfg = load(fws.home)
    roots = verifier.build_roots(cfg, [{"path": "projects/greeter"}])
    line = probe.with_workdir("PROBE: grep -c greet(name {workdir}/greeter.py => ^1$",
                              "projects/greeter")
    row = probe.run_line(line, roots)
    assert probe.verdict_of(row) == "contradiction", row
    raw = probe.run_line("PROBE: grep -c greet(name {workdir}/greeter.py => ^1$", roots)
    assert raw["error"] and raw["error"].startswith("refused"), raw    # never matched unsubstituted


def test_clone_is_plumbing_only_and_never_runs_a_hook(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    git(target, "init", "-q", "-b", "main")
    (target / "a.py").write_text("print('a')\n")
    (target / ".gitattributes").write_text("*.py filter=evil\n")
    git(target, "add", "-A")
    git(target, "commit", "-qm", "base")
    marker = tmp_path / "HOOK-RAN"
    hook = target / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    git(target, "config", "filter.evil.smudge", f"sh -c 'touch {marker}; cat'")
    git(target, "config", "core.hooksPath", str(target / ".git" / "hooks"))
    base = clone.target_tip(target)
    dest = tmp_path / "t@5"
    assert clone.create(target, dest, base) == "created"
    assert (dest / "a.py").read_text() == "print('a')\n" and not marker.exists()
    assert git_out(dest, "rev-parse", "HEAD") == base
    assert git_out(dest, "status", "--porcelain") == ""
    assert not (dest / ".git" / "hooks").exists()                # no template hooks
    assert clone.create(target, dest, base) == "kept"           # a re-claim keeps the work
    with pytest.raises(clone.CloneError, match="not this job's clone"):
        clone.create(target, dest, "0" * 40)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(clone.CloneError, match="not this job's clone"):
        clone.create(target, other, base)


def test_clone_refuses_a_tree_that_writes_into_dot_git(tmp_path, monkeypatch):
    """A crafted tree with a `.git/hooks/...` entry would plant a hook in the clone (git's own
    porcelain refuses to build one; a hand-made object store need not)."""
    from konstant.verify import holdout
    target = tmp_path / "t"
    target.mkdir()
    git(target, "init", "-q", "-b", "main")
    (target / "x").write_text("x\n")
    git(target, "add", "-A")
    git(target, "commit", "-qm", "base")
    base = clone.target_tip(target)
    real = holdout.tree
    monkeypatch.setattr(holdout, "tree", lambda project, commit: real(project, commit) + [
        ("100755", real(project, commit)[0][1], ".git/hooks/post-commit")])
    with pytest.raises(clone.CloneError, match="into a .git directory"):
        clone.create(target, tmp_path / "t@1", base)
    assert not (tmp_path / "t@1").exists()


@needs_jail
def test_claim_of_a_holdout_job_on_a_non_git_project_is_refused(fws):
    plain = fws.home / "projects" / "plain"
    plain.mkdir()
    fws.ok("project", "add", "plain")
    b = fws.src / "b.md"
    b.write_text("do it\n\nDoD:\n- x\nPROBE: test -f projects/plain/x => ^ok$\n")
    jid = json.loads(fws.ok("job", "add", "t", "--project", "plain", "--type", "code",
                            "--brief", b, "--json").stdout)["id"]
    from konstant.board import db
    from konstant.config import load
    with db.transaction(load(fws.home).db_path) as conn:      # sealed rows, as `holdout add`
        conn.execute("UPDATE jobs SET holdout_required=1 WHERE id=?", (jid,))
        for i in (1, 2):
            conn.execute("INSERT INTO holdouts (job_id, hid, kind, sha256, author_label) "
                         "VALUES (?,?,?,?,?)", (jid, f"H{i}", "proof", str(i) * 64, "owner"))
    res = fws.run("job", "claim", jid)
    assert res.returncode == 1 and "is not a git repository" in res.stderr, res.stderr
