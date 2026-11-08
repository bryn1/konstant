"""Size tiers (konstant/triage/tiers.py, docs/CONCEPTS.md "Triage"): each rule red-then-green, the
cap from the endpoint's real concurrency, the owner's override tag."""
from __future__ import annotations

import copy
import subprocess
import sys

import pytest

from konstant import catalog
from konstant.config import DEFAULTS
from konstant.gate.classify import classify
from konstant.triage import tiers

CAT = catalog.load()


def cfg(**harness):
    d = copy.deepcopy(DEFAULTS)
    d["harness"].update(harness)
    return d


def tier(task, data=None, bound=False):
    t, why = classify(task, CAT)
    return tiers.decide(task, t, why, CAT, data or cfg(max_concurrency=16, max_parallel=2),
                        bound=bound)


def test_small_is_inline_and_one_deliverable_is_agent():
    t, _w, tr = tier("what is the board?")
    assert t is None and tr.name == "inline" and tr.agents == 0
    t, _w, tr = tier("[type:code] add greet() to greet.py")
    assert t == "code" and tr.name == "agent" and tr.agents == 1


def test_fanout_counts_independent_parts_red_below_the_minimum():
    _t, _w, tr = tier("[type:code] add retries to client.py, server.py and worker.py")
    assert tr.name == "fanout" and tr.parts == 3 and tr.agents == 3, tr
    _t, _w, tr = tier("[type:code] add retries to client.py and server.py")      # red: 2 < 3
    assert tr.name == "agent", tr


def test_list_items_and_explicit_counts_are_parts_but_dod_rows_are_not():
    task = "[type:code] port these:\n- parser\n- lexer\n- printer\n- linter\n"
    assert tier(task)[2].name == "fanout"
    _t, _w, tr = tier("[type:code] refactor 12 modules to the new logger")
    assert tr.parts == 12 and tr.name == "max", tr          # 12 > cap 8 (16 slots / 2 phases)
    dod = ("[type:code] add greet()\nDoD:\n- greet() returns hello\n- the CLI prints it\n"
           "- README names it\nPROBE: test -f a.py => ^ok$\n")
    assert tier(dod)[2].name == "agent"                     # DoD rows are checks, not parts


def test_max_is_bounded_by_the_endpoint_slots_never_unbounded():
    _t, _w, tr = tier("[type:code] add type hints across the entire codebase",
                      cfg(max_concurrency=16, max_parallel=2))
    assert tr.name == "max" and tr.agents == 8 and tr.cap == 8, tr
    assert "max_concurrency 16" in tr.cap_source
    _t, _w, tr = tier("[type:code] add type hints across the entire codebase",
                      cfg(max_concurrency=4, max_parallel=1))
    assert tr.agents == 4
    _t, _w, tr = tier("[type:code] rename 50 modules", cfg(max_concurrency=6, max_parallel=2))
    assert tr.name == "max" and tr.agents == 3 < 50          # red: never one agent per part


def test_unknown_slots_assume_one_run_at_a_time():
    n, src = tiers.cap_of(cfg(max_concurrency=0, max_parallel=2)["harness"])
    assert n == 1 and "unset" in src
    _t, _w, tr = tier("[type:code] fix a.py, b.py, c.py, d.py", cfg(max_parallel=2))
    assert tr.name == "max" and tr.agents == 1


@pytest.mark.parametrize("task", [
    "[type:code] keep running until all tests pass: make the parser pass the suite",
    "[type:code] for a month straight, grow the CLI. DoD:\n- every command works\n"
    "PROBE: test -f cli.py => ^ok$",
])
def test_factory_needs_long_running_and_mechanical_acceptance(task):
    t, _w, tr = tier(task)
    assert t == "code" and tr.name == "factory", tr


def test_factory_refused_without_acceptance_for_infra_and_for_taste_work():
    _t, _w, tr = tier("[type:code] keep working on the app for a month and make it nicer")
    assert tr.name != "factory" and "no mechanical acceptance" in tr.note
    _t, _w, tr = tier("[type:infra] keep running until all checks pass on the deploy script")
    assert tr.name != "factory" and "decision" in tr.note
    _t, _w, tr = tier("[type:docs] keep going until all checks pass on the handbook")
    assert tr.name != "factory" and "delivers a doc" in tr.note


def test_owner_tag_overrides_and_a_bound_job_is_never_a_factory():
    assert tier("[type:code] [tier:max] add greet()")[2].agents == 8
    assert tier("[type:code] [tier:fanout] add greet()")[2].name == "fanout"
    t, why, tr = tier("[tier:agent] what does greet do?")
    assert t == "code" and why == "tier-tag" and tr.name == "agent"
    t, _w, tr = tier("[type:code] [tier:inline] add greet()")
    assert t is None and tr.name == "inline"
    _t, _w, tr = tier("[type:code] [tier:factory] add greet()", bound=True)
    assert tr.name == "agent" and "bound" in tr.why
    _t, _w, tr = tier("[type:code] [tier:huge] add greet()")
    assert tr.name == "agent" and "not a tier" in tr.note


def test_classify_cli_prints_the_tier_and_its_reason():
    res = subprocess.run([sys.executable, "-m", "konstant", "--json", "task", "classify",
                          "[type:code] add retries to a.py, b.py and c.py"],
                         capture_output=True, text=True)
    import json
    out = json.loads(res.stdout)
    assert out["tier"] in ("fanout", "max") and out["tier_why"] and out["cap_source"]
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "classify",
                          "[type:code] add greet()"], capture_output=True, text=True)
    assert res.stdout.splitlines()[1].startswith("tier=agent why=")


def test_runner_parallel_phases_never_exceed_the_endpoint_slots():
    from konstant.cli.task_run import max_parallel
    assert max_parallel({"max_parallel": 4, "max_concurrency": 2}) == 2
    assert max_parallel({"max_parallel": 4, "max_concurrency": 0}) == 4     # unknown: as set


def test_config_refuses_a_bad_triage_value(tmp_path):
    from konstant import config
    (tmp_path / "konstant.toml").write_text('[triage]\nresearch = "sometimes"\n')
    with pytest.raises(config.ConfigError, match="research"):
        config.load(tmp_path)
    (tmp_path / "konstant.toml").write_text("[harness]\nmax_concurrency = -1\n")
    with pytest.raises(config.ConfigError, match="max_concurrency"):
        config.load(tmp_path)
