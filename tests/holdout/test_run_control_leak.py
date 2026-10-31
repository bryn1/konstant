"""The negative control (3.2 step 2), the pinned no-network runs (3.6 steps 1-3) and the leak
scan (3.5), on a real git project and konstant's jail. No board: the functions are called
directly. Each has a `_red` (planted defect) and a `_green` twin."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from konstant import config
from konstant.holdout import leak, lint
from konstant.verify import holdout as runner
from tests.holdout.conftest import BASE_GREETER, BRIEF, H1, H2, git, needs_jail

C1, C2 = "khc-0123456789abcdef0123", "khc-ffffffffffffffffffff"


def sc(text, hid, canary):
    return lint.parse((text + f"CANARY: {canary}\n").encode(), hid)


@dataclass
class Proj:
    path: Path
    base: str
    cfg: object


@pytest.fixture()
def proj(tmp_path):
    ws = tmp_path / "ws"
    (ws / "var").mkdir(parents=True)
    p = ws / "projects" / "greeter"
    p.mkdir(parents=True)
    git(p, "init", "-q", "-b", "main")
    (p / "greeter.py").write_text(BASE_GREETER)
    git(p, "add", "-A")
    git(p, "commit", "-qm", "base")
    return Proj(p, git(p, "rev-parse", "HEAD").stdout.strip(), config.load(ws))


def commit(p, body: str, msg: str = "work") -> str:
    (p.path / "greeter.py").write_text(body)
    git(p.path, "commit", "-qam", msg)
    return git(p.path, "rev-parse", "HEAD").stdout.strip()


HONEST = '"""greeter: small greetings."""\n\n\ndef greet(name="world"):\n    return f"hello {name}"\n'
OVERFIT = '"""greeter: small greetings."""\n\n\ndef greet(name="world"):\n    return "hello world"\n'


@needs_jail
def test_negative_control_green(proj):
    assert runner.negative_control(proj.cfg, [sc(H1, "H1", C1), sc(H2, "H2", C2)], proj.path,
                                   proj.base) == []


@needs_jail
def test_negative_control_red(proj):
    vacuous = sc(H1.replace("print(greet('Ada'))", "print('hello Ada')"), "H3", C1)
    broken_reg = sc(H2.replace("greet().upper()", "greet('x')"), "H4", C2)
    found = runner.negative_control(proj.cfg, [vacuous, broken_reg], proj.path, proj.base)
    assert "VACUOUS: H3 passes before the work" in found
    assert any(r.startswith("REGRESSION FAILS: H4") for r in found)
    gone = sc(H2.replace("RUN: python3", "RUN: no-such-binary-xyz"), "H5", C2)
    assert any(r.startswith("UNRUNNABLE: H5") for r in
               runner.negative_control(proj.cfg, [gone], proj.path, proj.base))


@needs_jail
def test_runs_are_pinned_to_the_commit_not_the_live_tree(proj):
    good = commit(proj, HONEST)
    (proj.path / "greeter.py").write_text(OVERFIT)            # the live tree says otherwise
    rows = runner.run_set(proj.cfg, [sc(H1, "H1", C1)], proj.path, good)
    assert rows[0]["passed"] and rows[0]["commit"] == good and rows[0]["net"] is False
    assert (proj.path / "greeter.py").read_text() == OVERFIT  # nothing written into the project
    bad = commit(proj, OVERFIT, "overfit")
    assert not runner.run_set(proj.cfg, [sc(H1, "H1", C1)], proj.path, bad)[0]["passed"]


@needs_jail
def test_runs_have_no_network_and_leave_nothing(proj):
    probe = ('RUN: python3 -c "import socket, os; s = socket.socket(); s.settimeout(2); '
             "r = s.connect_ex(('192.0.2.1', 53)); open('trace.txt', 'w').write('x'); "
             "w = os.access('/tmp', os.W_OK); open(os.environ['TMPDIR'] + '/t', 'w').write('x'); "
             "print('net' if r == 0 else 'nonet', 'tmp-writable' if w else 'tmp-ro')\"")
    text = H2.replace(H2.splitlines()[2], probe).replace("HELLO WORLD", "nonet tmp-ro")
    c = commit(proj, HONEST)
    before = set(os.listdir("/tmp"))
    row = runner.run_set(proj.cfg, [sc(text, "H1", C1)], proj.path, c)[0]
    assert row["passed"], row                    # no route out; /tmp read-only but its own TMPDIR
    assert not (proj.path / "trace.txt").exists()         # its writes went to the temp tree
    assert not {x for x in set(os.listdir("/tmp")) - before if x.startswith("konstant-")}


@needs_jail
def test_runs_cannot_read_the_sealed_store(proj):
    store = proj.cfg.home / "var" / "holdout" / "2"
    store.mkdir(parents=True)
    (store / "H1.scenario").write_text("secret\n")
    text = H2.replace(H2.splitlines()[2], 'RUN: python3 -c "import os; print(len(os.listdir('
                      f"'{store.parent}')))\"").replace("HELLO WORLD", "0")
    c = commit(proj, HONEST)
    assert runner.run_set(proj.cfg, [sc(text, "H1", C1)], proj.path, c)[0]["passed"]


def test_runs_refuse_without_the_jail(proj, monkeypatch):
    monkeypatch.setenv("KONSTANT_NO_JAIL", "1")
    runner.jail_mod.available.cache_clear()
    try:
        with pytest.raises(runner.HoldoutError, match="holdouts need a confined phase"):
            runner.run_set(proj.cfg, [sc(H1, "H1", C1)], proj.path, proj.base)
    finally:
        runner.jail_mod.available.cache_clear()


def test_materialise_writes_raw_blobs_and_refuses_nothing_else(proj, tmp_path):
    (proj.path / ".gitattributes").write_text("*.py filter=evil\n")
    git(proj.path, "config", "filter.evil.smudge", f"touch {tmp_path}/SMUDGE-RAN; cat")
    git(proj.path, "add", ".gitattributes")
    c = commit(proj, HONEST)
    dest = tmp_path / "tree"
    dest.mkdir()
    runner.materialise(proj.path, c, dest)
    assert (dest / "greeter.py").read_text() == HONEST
    assert not (tmp_path / "SMUDGE-RAN").exists()          # no filter ran (F-04)


def _scan(proj, scs, c, runs=(), trail=(), brief=BRIEF):
    return leak.scan(proj.cfg.home, scs, project=proj.path, base=proj.base, commit=c,
                     runs=list(runs), trail=list(trail), brief=brief)


def test_leak_scan_green(proj):
    c = commit(proj, HONEST)
    assert _scan(proj, [sc(H1, "H1", C1), sc(H2, "H2", C2)], c) == ([], [])


def test_leak_scan_red_canary_in_the_diff_and_the_trail(proj):
    c = commit(proj, HONEST + f"# {C1}\n")
    leaks, _s = _scan(proj, [sc(H1, "H1", C1), sc(H2, "H2", C2)], c,
                      trail=[{"id": 7, "body": f"pasted {C2}"}])
    assert "LEAK: canary of H1 found in greeter.py" in leaks
    assert "LEAK: canary of H2 found in trail row 7" in leaks


def test_leak_scan_red_canary_in_a_run_log_and_out(proj):
    ws = proj.cfg.home
    rd = ws / "var" / "runs" / "r1"
    (rd / "phases").mkdir(parents=True)
    out = rd / "out"
    out.mkdir()
    (rd / "record.json").write_text('{"out": "%s"}' % out)
    (rd / "phases" / "02-coder.log").write_text(f"saw {C1}\n")
    (out / "notes.md").write_text(f"{C2}\n")
    outside = proj.cfg.home.parent / "elsewhere"           # not under var/runs: never read
    (outside / "phases").mkdir(parents=True)
    leaks, _s = _scan(proj, [sc(H1, "H1", C1), sc(H2, "H2", C2)], commit(proj, HONEST),
                      runs=[rd, outside])
    assert "LEAK: canary of H1 found in var/runs/r1/phases/02-coder.log" in leaks
    assert any(x.startswith("LEAK: canary of H2 found in OUT notes.md") for x in leaks)


def test_leak_scan_red_literal_on_an_added_line(proj):
    c = commit(proj, HONEST + 'ANSWERS = {"Ada": "hello Ada"}\n')
    _l, suspects = _scan(proj, [sc(H1, "H1", C1)], c)
    assert suspects == ["LEAK-SUSPECT: a literal of H1 appears on an added line of greeter.py"]


def test_leak_scan_green_literal_in_the_brief_is_not_suspect(proj):
    c = commit(proj, HONEST + "# hello Ada\n")
    brief = BRIEF + "\nexample: hello Ada\n"
    assert _scan(proj, [sc(H1, "H1", C1)], c, brief=brief)[1] == []
    assert os.path.isdir(proj.path)
