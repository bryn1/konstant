"""The scenario writer's isolation (docs/LEVEL5.md 3.4, B9; wave L5-3): its prompt names no job
clone, OUT or run path; its run dir, home and drafts lie inside the sealed store; inside its jail
var/runs/, every job clone, the board DB, the tokens and the other jobs' holdouts are masked, and
only its own drafts dir is writable. A harness whose home konstant cannot relocate is refused."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from konstant import jail, machinery
from konstant.harnesses import adapter
from konstant.harnesses.base import Phase
from tests.factory.test_intake import GOAL, intake
from tests.holdout.conftest import make_ws, needs_jail


@pytest.fixture()
def iws(tmp_path):
    w = make_ws(tmp_path)
    (w.src / "goal.toml").write_text(GOAL)
    assert w.run("--as", "owner", "goal", "add", w.src / "goal.toml").returncode == 0
    clone = w.home / "projects" / "greeter@99"              # another job's clone, with content
    clone.mkdir()
    (clone / "producer-output.py").write_text("print('the producer was here')\n")
    yield w
    w.run("board", "stop")


@needs_jail
def test_B9_scenario_prompt_and_run_dir(iws):
    res = intake(iws)
    assert res.returncode == 0, res.stderr[-2000:]
    store = iws.home / "var" / "holdout"
    for job in (2, 3):
        runs = sorted((store / str(job) / "runs").iterdir())
        assert runs, f"no scenario run dir under the store for job {job}"
        prompt = next((runs[-1] / "prompts").glob("*.md")).read_text()
        assert "@" not in re.sub(r"[\w.+-]+@example\.com", "", prompt)      # no job clone
        named = {n.rstrip(":.,") for n in re.findall(re.escape(str(iws.home)) + r"[^\s`'\")]*", prompt)}
        assert named == {str(store / str(job) / "drafts"),                 # only its drafts
                         str(iws.home / "projects" / "greeter")}, named   # and the target
        assert "KONSTANT-OUT" not in prompt and "KONSTANT-RUN" not in prompt
        assert f"KONSTANT-DRAFTS: {store / str(job) / 'drafts'}" in prompt
        assert not (store / str(job) / "drafts").exists()        # sealed and removed
        assert not (store / str(job) / "home").exists()          # the harness home is gone
        log = next((runs[-1] / "phases").glob("*.log")).read_text()
        sees = dict(ln[len("scenario-sees: "):].split(": ", 1) for ln in log.splitlines()
                    if ln.startswith("scenario-sees: "))
        assert sees["var/runs"] == "[]"                          # the intake run is masked
        assert sees["secrets"] == "[]"                           # no token at all
        assert "denied" in sees["board db"]
        assert sees["clone greeter@99"] == "[]"                  # another job's clone masked
        assert sees["store"] == f"['{job}']"                     # only its own job dir shows
    for run in (iws.home / "var" / "runs").iterdir():           # no scenario run outside the store
        assert not any("scenario" in p.name for p in (run / "phases").glob("*"))


def phase(ws: Path, hide=(), tokens=()) -> Phase:
    jd = ws / "var" / "holdout" / "2"
    drafts = jd / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    (jd / "runs" / "r" / "prompts").mkdir(parents=True, exist_ok=True)
    pf = jd / "runs" / "r" / "prompts" / "scenario-a1.md"
    pf.write_text("p")
    return Phase({"workspace": ws, "cwd": drafts, "run_dir": jd / "runs" / "r", "prompt": "p",
                  "prompt_file": pf, "agent": "scenario-writer", "out": None},
                 factory=True, identity="scenario", home_base=jd / "home", tokens=tokens,
                 hide=tuple(hide))


@pytest.fixture()
def ws(tmp_path):
    w = tmp_path / "ws"
    for d in ("var/secrets", "var/runs/r1", "var/holdout/3", "projects/demo@7"):
        (w / d).mkdir(parents=True)
    for t in machinery.ALL_TOKENS:
        (w / "var" / "secrets" / t).write_text("t\n")
    return w


def binds(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


@needs_jail
def test_scenario_jail_masks_the_store_and_binds_only_its_drafts_green(ws):
    ad = adapter("dsh")
    ph = phase(ws, hide=[ws / "var" / "runs", ws / "projects" / "demo@7"])
    ad.prepare(ph)
    try:
        argv = ad.confine(["tool"], ph)
    finally:
        ad.cleanup(ph)
    store = str((ws / "var" / "holdout").resolve())
    drafts = str((ws / "var" / "holdout" / "2" / "drafts").resolve())
    tmpfs = binds(argv, "--tmpfs")
    assert store in tmpfs                                    # the store is masked ...
    assert argv.index(drafts) > argv.index(store)            # ... and the drafts bound AFTER it
    assert str((ws / "var" / "runs").resolve()) in tmpfs
    assert str((ws / "projects" / "demo@7").resolve()) in tmpfs
    assert not [b for b in binds(argv, "--ro-bind") if b.endswith(".token")]    # no token
    pf = str((ws / "var/holdout/2/runs/r/prompts/scenario-a1.md").resolve())
    assert pf in binds(argv, "--ro-bind")                    # its prompt, read-only


@needs_jail
def test_red_twin_a_writable_dir_inside_a_mask_used_to_unmask_it(ws):
    """Before L5-3 jail.wrap skipped a mask that held a writable bind: the scenario writer's
    drafts inside var/holdout would have exposed every job's sealed scenarios. Inside a real
    jail: a sibling job's scenario is unreadable, the drafts dir writable."""
    (ws / "var" / "holdout" / "3" / "H1.scenario").write_text("SECRET SCENARIO\n")
    drafts = ws / "var" / "holdout" / "2" / "drafts"
    drafts.mkdir(parents=True)
    probe = (f"import pathlib; p=pathlib.Path({str(ws / 'var/holdout/3/H1.scenario')!r}); "
             f"print('READ' if p.exists() else 'MASKED'); "
             f"pathlib.Path({str(drafts / 'd.scenario')!r}).write_text('x'); print('WROTE')")
    argv = jail.wrap([sys.executable, "-c", probe], rw=[drafts], hide=jail.hidden(ws), home=ws,
                     cwd=drafts)          # no private /tmp: the store mask alone must hide it
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["MASKED", "WROTE"], out.stdout + out.stderr
    assert (drafts / "d.scenario").read_text() == "x"


def test_scenario_writer_refuses_a_command_template(tmp_path):
    from konstant import catalog, config
    from konstant.holdout import author
    (tmp_path / "konstant.toml").write_text('[harness]\nname = "command"\ncommand = "tool {prompt_file}"\n')
    cfg = config.load(tmp_path)
    with pytest.raises(author.AuthorRefused, match="cannot relocate"):
        author.writer_harness(cfg, catalog.load())
