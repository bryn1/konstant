"""The first level-5 independent review (docs/build/REVIEW-L5-R1.md): one red-then-green test per
finding H-01..H-09. Each was RED on 8f40c31 for the reviewer's reproduction and GREEN after the
wave L5-F1 fix; the "should stay allowed" twins stay green on both.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from konstant import confinement, jail, machinery
from konstant.holdout import leak, lint
from konstant.verify import holdout as runner
from tests.factory.conftest import logs, run, sealed_job
from tests.holdout.conftest import BASE_GREETER, H1, H2, git, needs_jail

C1, C2 = "khc-0123456789abcdef0123", "khc-ffffffffffffffffffff"
HONEST = '"""greeter: small greetings."""\n\n\ndef greet(name="world"):\n    return f"hello {name}"\n'
BROKEN = '"""greeter: small greetings."""\n\n\ndef greet(name="world"):\n    return "BROKEN"\n'


def sc(text, hid, canary):
    return lint.parse((text + f"CANARY: {canary}\n").encode(), hid)


# --- H-01: konstant never runs a program a phase could have planted on PATH -------------------

def _plant(d: Path, name: str, sentinel: Path) -> None:
    p = d / name
    p.write_text(f"#!/bin/sh\necho planted >> {sentinel}\nexec /usr/bin/{name} \"$@\"\n")
    p.chmod(0o755)


def test_H01_konstant_git_ignores_a_planted_PATH_entry(tmp_path):
    """A user-writable PATH dir (as an open factory phase would write) holds a malicious `git`.
    konstant's own git plumbing must resolve the trusted system git, not the planted one."""
    from konstant import tools
    from konstant.gate.rules import common
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    bad = tmp_path / "evilbin"
    bad.mkdir()
    sentinel = tmp_path / "RAN"
    for name in ("git", "python3", "node", "dsh", "sh"):
        _plant(bad, name, sentinel)
    old = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{bad}:{old}"
    try:
        assert tools.which("git") == "/usr/bin/git"              # not the planted one
        assert bad not in Path(tools.trusted_path()).parents and str(bad) not in tools.trusted_path()
        r = common.git(repo, "rev-parse", "--verify", "HEAD")
        assert r.returncode == 0 and r.stdout.strip()
    finally:
        os.environ["PATH"] = old
    assert not sentinel.exists(), "konstant ran a program planted on PATH"


def test_H01_trusted_path_is_root_owned_dirs_only(tmp_path):
    from konstant import tools
    for d in tools.system_dirs():
        st = os.stat(d)
        assert st.st_uid == 0 and not st.st_mode & 0o022, d


# --- H-02: a replace ref cannot make a broken commit pass -------------------------------------

def _repo(tmp_path) -> Path:
    from konstant import config
    ws = tmp_path / "ws"
    (ws / "var").mkdir(parents=True)
    p = ws / "projects" / "greeter"
    p.mkdir(parents=True)
    git(p, "init", "-q", "-b", "main")
    (p / "greeter.py").write_text(BASE_GREETER)
    git(p, "add", "-A")
    git(p, "commit", "-qm", "base")
    return ws


@needs_jail
def test_H02_replace_ref_commit_is_refused_not_run(tmp_path):
    """The reviewer's repro: commit G (good), commit B (broken), `git replace B G`, stage good.
    Running holdouts on B must NOT read G's tree (refused, or the real broken tree)."""
    from konstant import config
    ws = _repo(tmp_path)
    p = ws / "projects" / "greeter"
    (p / "greeter.py").write_text(HONEST)
    git(p, "commit", "-qam", "good")
    good = git(p, "rev-parse", "HEAD").stdout.strip()
    (p / "greeter.py").write_text(BROKEN)
    git(p, "commit", "-qam", "broken")
    broken = git(p, "rev-parse", "HEAD").stdout.strip()
    git(p, "replace", "-f", broken, good)                    # B now reads as G by default
    (p / "greeter.py").write_text(HONEST)                    # a clean worktree
    cfg = config.load(ws)
    with pytest.raises(runner.HoldoutError) as exc:
        runner.run_set(cfg, [sc(H1, "H1", C1)], p, broken)
    assert "replace" in str(exc.value)


@needs_jail
def test_H02_a_clean_clone_still_runs_green(tmp_path):
    from konstant import config
    ws = _repo(tmp_path)
    p = ws / "projects" / "greeter"
    (p / "greeter.py").write_text(HONEST)
    git(p, "commit", "-qam", "good")
    good = git(p, "rev-parse", "HEAD").stdout.strip()
    rows = runner.run_set(config.load(ws), [sc(H1, "H1", C1)], p, good)
    assert rows[0]["passed"] and rows[0]["hid"] == "H1"


# --- H-03: the sealed memory pool is unreadable by producers ----------------------------------

def test_H03_var_memory_is_sealed_and_not_a_phase_read(tmp_path):
    assert "var/memory" in machinery.SEALED and "var/memory" in machinery.DIRS
    ws = tmp_path / "ws"
    (ws / "var/memory").mkdir(parents=True)
    (ws / "var/memory/index.db").write_text("sealed note body: zebra-quokka-7731\n")
    argv = jail.wrap(["true"], hide=jail.hidden(ws), home=ws)
    masked = any(argv[i] == "--tmpfs" and argv[i + 1] == str((ws / "var/memory").resolve())
                 for i in range(len(argv) - 1))
    assert masked or not jail.available()


def test_H03_sealed_note_path_carries_no_text(mb):
    """A sealed-pool note's path (recorded in the phase-readable memory_writes) must not be built
    from the note's text, or the path itself leaks the lesson through the one-way glass."""
    from konstant.board import db
    lesson = "zebra-quokka-7731 holdouts like unusual names"
    r = mb.store("verifier", lesson, title="sealed lesson zebra-quokka-7731")
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    assert path.startswith("sealed/verifier/")
    assert "zebra" not in path and "quokka" not in path and "lesson" not in path
    with db.reading(mb.cfg.db_path) as conn:
        rows = [dict(x) for x in conn.execute("SELECT path FROM memory_writes WHERE pool='sealed'")]
    assert rows and all("zebra" not in x["path"] and "quokka" not in x["path"] for x in rows)


def test_H03_shared_note_path_is_still_its_title_green(mb):
    r = mb.note("worker", "Board port notes", "the board port clashed once")
    assert r.status_code == 200 and r.json()["path"] == "shared/worker/Board port notes.md"


# --- H-04: an external holdout store is masked like the in-workspace one -----------------------

def test_H04_external_store_is_sealed(tmp_path):
    ws = tmp_path / "ws"
    store = tmp_path / "external-store"
    store.mkdir()
    (ws).mkdir()
    (ws / "konstant.toml").write_text(f'[holdout]\nstore = "{store}"\n')
    ext = machinery.external_store(ws)
    assert ext == [store.resolve()] or ext == [store]
    sealed = [str(p) for p in machinery.sealed(ws)]
    assert str(store.resolve()) in sealed or str(store) in sealed
    hidden = [os.path.realpath(h) for h in jail.hide_core(ws)]
    assert os.path.realpath(str(store)) in hidden


def test_H04_default_store_adds_no_external(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "konstant.toml").write_text('[holdout]\nstore = "var/holdout"\n')
    assert machinery.external_store(ws) == []


# --- H-05: a closed phase's environment is an allowlist ---------------------------------------

DUMMY_HOST = {"PATH": "/usr/bin", "HOME": "/home/x", "LC_ALL": "C",
              "REVIEW_DUMMY_SECRET_KEY": "s1", "REVIEW_DUMMY_API_TOKEN": "s2",
              "GITHUB_TOKEN": "s3", "SESSION_MESSAGING": "s4",  # an arbitrary-name secret
              "ANTHROPIC_API_KEY": "model-key"}


def test_H05_closed_env_is_an_allowlist():
    kept = confinement.CLOSED.filter_host_env(DUMMY_HOST, adapter_keys=("ANTHROPIC_API_KEY",))
    assert kept.get("PATH") and kept.get("HOME") and kept.get("LC_ALL") == "C"
    assert kept.get("ANTHROPIC_API_KEY") == "model-key"       # the harness's own key passes
    for leaked in ("REVIEW_DUMMY_SECRET_KEY", "REVIEW_DUMMY_API_TOKEN", "GITHUB_TOKEN",
                   "SESSION_MESSAGING"):
        assert leaked not in kept, leaked                     # incl. the arbitrary-name one


def test_H05_researcher_and_scenario_allowlist_even_under_open():
    openp = confinement.parse({"profile": "open"})
    assert openp.for_phase("researcher").allowlists_env()      # researcher stays closed
    assert openp.for_phase("scenario").allowlists_env()
    assert "SESSION_MESSAGING" not in openp.for_phase("researcher").filter_host_env(DUMMY_HOST)
    assert "SESSION_MESSAGING" not in openp.for_phase("scenario").filter_host_env(DUMMY_HOST)


def test_H05_open_producer_passes_env_by_design_green():
    openp = confinement.parse({"profile": "open"})
    kept = openp.for_phase("worker").filter_host_env(DUMMY_HOST)
    assert kept.get("SESSION_MESSAGING") == "s4"              # open passes the host by design
    assert kept.get("REVIEW_DUMMY_SECRET_KEY") == "s1"        # (credentials = ["*"] for open)


def test_H05_passthrough_names_are_kept():
    kept = confinement.CLOSED.filter_host_env(
        {"FAKE_HARNESS_MODE": "m", "SESSION_MESSAGING": "s"}, passthrough=("FAKE_*",))
    assert kept.get("FAKE_HARNESS_MODE") == "m" and "SESSION_MESSAGING" not in kept


@needs_jail
def test_H05_live_closed_factory_phase_sees_no_host_secret(fws, tmp_path):
    """A factory phase run from a shell carrying dummy secrets must see none of them (closed)."""
    probe = fws.src / "env_probe.py"
    probe.write_text(
        "import os\n"
        "names = ['REVIEW_DUMMY_SECRET_KEY','REVIEW_DUMMY_API_TOKEN','SESSION_MESSAGING']\n"
        "print('env-probe: ' + ' '.join(f'{n}={\"Y\" if os.environ.get(n) else \"n\"}'"
        " for n in names), flush=True)\n")
    (fws.src / "sitecustomize.py").write_text(
        "import os, runpy, sys\n"
        "a = ' '.join(sys.argv)\n"
        "if os.environ.get('KONSTANT_IN_TASK') == '1' and '--dump-config' not in a and \\\n"
        "        any(s in a for s in ('fake_harness.py','stub_cli.py','stub_dsh.py')):\n"
        f"    runpy.run_path({str(probe)!r})\n")
    jid = sealed_job(fws)
    res, rd = run(fws, "command", jid,
                  PYTHONPATH=f"{fws.src}:{os.environ.get('PYTHONPATH', '')}",
                  REVIEW_DUMMY_SECRET_KEY="dummy1", REVIEW_DUMMY_API_TOKEN="dummy2",
                  SESSION_MESSAGING="dummy3")
    lines = [ln for ln in logs(rd).splitlines() if ln.startswith("env-probe: ")]
    assert lines, logs(rd)[-2000:]
    for ln in lines:
        assert "=Y" not in ln, ln
    assert res.returncode == 0, res.stderr[-2000:]


# --- H-06: a level-4 phase cannot poison the catalog for a later factory run ------------------

@needs_jail
def test_H06_catalog_drift_refuses_a_factory_run(fws):
    """A level-4 phase edits catalog/agents/tester.md; the next factory run must refuse (the
    manifest `agents sync` recorded no longer matches), instead of composing from it."""
    jid = sealed_job(fws)
    tester = fws.home / "catalog" / "agents" / "tester.md"
    tester.write_text(tester.read_text() + "\nINJECTED-BY-A-LEVEL4-PHASE\n")   # the poisoning
    res, rd = run(fws, "command", jid)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "catalog/ changed outside `agents sync`" in res.stderr
    assert fws.json("job", "show", jid)["status"] == "queued"   # nothing ran
    assert rd is None or not list(rd.glob("phases/*.log"))


@needs_jail
def test_H06_after_resync_the_factory_run_proceeds_green(fws):
    jid = sealed_job(fws)
    tester = fws.home / "catalog" / "agents" / "tester.md"
    tester.write_text(tester.read_text() + "\na deliberate edit\n")
    fws.ok("agents", "sync")                                   # re-record the manifest
    res, _rd = run(fws, "command", jid)
    assert res.returncode == 0, res.stderr[-2000:]
    assert fws.json("job", "show", jid)["status"] == "verified"


# --- H-07: renaming .git cannot defeat the read-only git config -------------------------------

@needs_jail
def test_H07_cannot_rename_git_or_write_its_config(tmp_path):
    ws = tmp_path / "ws"
    (ws / "var").mkdir(parents=True)
    repo = ws / "projects" / "greeter"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    script = ("cd '%s'; mv .git gitold 2>/dev/null && echo RENAMED || echo RENAME-DENIED; "
              "echo '[alias]' >> .git/config 2>/dev/null && echo CONFIG-WROTE || "
              "echo CONFIG-DENIED; : > .git/newfile 2>/dev/null && echo NEWFILE-WROTE || "
              "echo NEWFILE-DENIED; echo x > work.txt && echo WORK-WROTE" % repo)
    argv = jail.wrap(["/bin/sh", "-c", script], rw=(repo,), home=ws, cwd=repo)
    out = subprocess.run(argv, capture_output=True, text=True).stdout
    assert "RENAME-DENIED" in out and "RENAMED" not in out, out
    assert "CONFIG-DENIED" in out and "CONFIG-WROTE" not in out, out
    assert "WORK-WROTE" in out, out                            # ordinary work still writable
    assert (repo / ".git").is_dir() and not (repo / "gitold").exists()


# --- H-08: `memory show` works --------------------------------------------------------------

def test_H08_memory_show_cli_does_not_crash(hws):
    """`konstant memory show PATH` drives the real client (Client.get with a `path` query param),
    where the reviewer hit `TypeError: Client.get() got multiple values for argument 'path'`."""
    store = hws.ok("memory", "store", "the board port 8470 clashes with the proxy",
                   "--title", "Port note", "--json")
    path = json.loads(store.stdout)["path"]
    show = hws.run("memory", "show", path)
    assert show.returncode == 0, show.stderr
    assert "8470" in show.stdout and "TypeError" not in show.stderr


def test_H08_client_get_accepts_a_path_param():
    from konstant.client import Client
    seen = {}

    class C(Client):
        def request(self, method, route, body=None, params=None):
            seen.update(route=route, params=params)
            return {}
    C("http://x").get("/api/memory/note", path="sealed/verifier/x.md")
    assert seen["route"] == "/api/memory/note" and seen["params"] == {"path": "sealed/verifier/x.md"}


# --- H-09: the scans catch common transforms --------------------------------------------------

def test_H09_transforms_detects_encoded_split_reversed():
    from konstant.holdout import transforms
    n = "hello Ada Lovelace"
    assert transforms.appears(n, 'x = "hel" + "lo A" + "da Lovelace"')     # split
    assert transforms.appears(n, "HELLO ADA LOVELACE")                     # case
    assert transforms.appears(n, "reversed: ecalevoL adA olleh")           # reversed
    assert transforms.appears(n, transforms.encoded_forms(n)[0])           # base64/hex/url
    assert not transforms.appears(n, "an unrelated greeting line")


def _proj_with(tmp_path, added: str):
    from konstant import config
    ws = tmp_path / "ws"
    (ws / "var").mkdir(parents=True)
    p = ws / "projects" / "greeter"
    p.mkdir(parents=True)
    git(p, "init", "-q", "-b", "main")
    (p / "greeter.py").write_text(HONEST)
    git(p, "add", "-A")
    git(p, "commit", "-qm", "base")
    base = git(p, "rev-parse", "HEAD").stdout.strip()
    (p / "greeter.py").write_text(HONEST + added)
    git(p, "commit", "-qam", "work")
    commit = git(p, "rev-parse", "HEAD").stdout.strip()
    return config.load(ws), p, base, commit


def test_H09_leak_scan_catches_a_split_literal(tmp_path):
    cfg, p, base, commit = _proj_with(tmp_path, 'ANSWER = "hello " + "Ada Lovelace"\n')
    scen = sc(H1.replace("hello Ada", "hello Ada Lovelace"), "H1", C1)
    _l, suspects = leak.scan(cfg.home, [scen], project=p, base=base, commit=commit, runs=[],
                             trail=[], brief="")
    assert any("H1" in s for s in suspects), suspects


def test_H09_leak_scan_green_when_no_literal_appears(tmp_path):
    cfg, p, base, commit = _proj_with(tmp_path, 'X = 1\n')
    scen = sc(H1.replace("hello Ada", "hello Ada Lovelace"), "H1", C1)
    _l, suspects = leak.scan(cfg.home, [scen], project=p, base=base, commit=commit, runs=[],
                             trail=[], brief="")
    assert not suspects


def test_H09_memory_scan_refuses_a_transformed_literal(mb):
    mb.seal_scenario(5, "SCENARIO: s\nKIND: proof\nRUN: python3 -c \"print('hello Ada Lovelace')\"\n"
                        "EXPECT_EXIT: 0\nEXPECT_OUT: hello Ada Lovelace\nHINT: h\n"
                        "CANARY: khc-0123456789abcdef0123\n")
    r = mb.store("worker", 'note: the trick is "hel"+"lo Ada Lovelace" split up')
    assert r.status_code == 422, r.text
    assert "literal" in (r.json().get("detail", "")).lower() or r.status_code == 422


@needs_jail
def test_H01_a_planted_usercustomize_does_not_load_into_a_scenario_run(tmp_path, monkeypatch):
    """An open phase can write under $HOME; Python's user site there (usercustomize) would load
    into the system python3 a scenario RUN starts and could fake its output. Scenario runs get a
    private HOME and PYTHONNOUSERSITE=1."""
    from konstant import config
    import site
    home = tmp_path / "home"
    rel = Path(site.getusersitepackages()).relative_to(Path(os.path.expanduser("~")))
    usite = home / rel
    usite.mkdir(parents=True)
    (usite / "usercustomize.py").write_text(
        "import os, sys\nsys.stdout.write('hello Ada\\n')\nsys.stdout.flush()\nos._exit(0)\n")
    monkeypatch.setenv("HOME", str(home))
    ws = _repo(tmp_path)
    p = ws / "projects" / "greeter"
    base = git(p, "rev-parse", "HEAD").stdout.strip()             # greet() takes no name
    rows = runner.run_set(config.load(ws), [sc(H1, "H1", C1)], p, base)
    assert not rows[0]["passed"], "a planted usercustomize faked the scenario's output"


def test_H05_harness_run_keeps_the_endpoint_key_and_drops_the_rest(tmp_path, monkeypatch):
    """Through the real Harness.run (a closed level-4 phase): the variable [harness.endpoint]
    api_key_env names reaches the phase (the harness needs it), an arbitrary host secret does not."""
    from konstant.gate.harness import Harness
    monkeypatch.setenv("LOCAL_ENDPOINT_KEY", "endpoint-key")
    monkeypatch.setenv("SESSION_MESSAGING", "host-secret")
    monkeypatch.delenv("KONSTANT_ENV_PASSTHROUGH", raising=False)
    script = ("import os; print('KEY', os.environ.get('LOCAL_ENDPOINT_KEY'), "
              "'SECRET', os.environ.get('SESSION_MESSAGING'))")
    h = Harness(f"{sys.executable} -c \"{script}\" {{prompt_file}}", workspace=tmp_path,
                endpoint={"base_url": "", "api_key_env": "LOCAL_ENDPOINT_KEY"})
    res = h.run("P", agent="coder", cwd=tmp_path, run_dir=tmp_path / "run", label="01-x")
    log = open(res.log).read()
    assert "KEY endpoint-key" in log and "SECRET None" in log, log


@needs_jail
def test_H04_doctor_proves_the_store_masked_two_sided(tmp_path, monkeypatch):
    """jail_proof lists the store from inside a phase jail. Green: the real masks -> nothing to
    report. Red twin: with the masks removed (what an unmasked external store looked like before
    the fix) the same check reports it READABLE, so the PASS is earned, not printed."""
    from konstant import config
    from konstant.holdout import store
    ws = tmp_path / "ws"
    ext = tmp_path / "ext-store"
    (ext / "4").mkdir(parents=True)
    (ext / "4" / "H1.scenario").write_text("EXPECT_OUT: hello Ada\n")
    ws.mkdir()
    (ws / "konstant.toml").write_text(f'[board]\nport = 9101\n[holdout]\nstore = "{ext}"\n')
    cfg = config.load(ws)
    assert store.jail_proof(cfg) is None
    monkeypatch.setattr(jail, "hide_core", lambda home: [])
    found = store.jail_proof(cfg)
    assert found and "READABLE" in found
