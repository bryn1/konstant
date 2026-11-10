"""The sample project and goal (examples/greeter/; docs/LEVEL5.md 7, wave L5-6) stay what the
level-5 proof (tests/e2e/factory.sh) and the README's "Try the factory" rely on: the goal file is
valid with max_attempts as its only limit and a README post-ship probe, the project's own test
passes on the base, and the base module is the one the fake harness and the holdout fixtures
assume (a greet() without a name, so the held-out proof fails on the base)."""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from konstant.factory import goal
from tests.holdout.conftest import BASE_GREETER, REPO

EX = REPO / "examples" / "greeter"


def test_sample_goal_is_valid_with_one_limit():
    spec = goal.parse((EX / "goal.toml").read_text())
    assert spec["goal"]["id"] == "greeter" and spec["goal"]["project"] == "greeter"
    limits = {k: v for k, v in spec["limits"].items() if v not in (0, "0")}
    assert limits == {"max_attempts": 3}
    assert spec["ship"]["target"] == "branch"                    # the public default
    assert spec["ship"]["post_probes"] == ["PROBE: test -f {workdir}/README.md => ^ok$"]


def test_sample_goal_with_a_typo_is_refused_red():
    text = (EX / "goal.toml").read_text().replace("max_attempts", "max_atempts", 1)
    with pytest.raises(goal.GoalError):
        goal.parse(text)


def test_sample_project_is_the_fixtures_base(tmp_path):
    assert (EX / "greeter.py").read_text() == BASE_GREETER
    assert sorted(p.name for p in EX.iterdir() if p.name != "__pycache__") == [
        "README.md", "goal.toml", "greeter.py", "test_greeter.py"]
    proj = tmp_path / "greeter"                       # a copy: nothing is written into examples/
    shutil.copytree(EX, proj)
    env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        str(proj / "test_greeter.py")], capture_output=True, text=True,
                       cwd=str(proj), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    held_out = subprocess.run([sys.executable, "-c", "from greeter import greet; greet('Ada')"],
                              capture_output=True, text=True, cwd=str(proj), env=env)
    assert held_out.returncode != 0                 # the base cannot greet by name yet
