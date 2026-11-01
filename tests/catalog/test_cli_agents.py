"""`konstant agents list|sync` as a user runs them (subprocess, temp workspace)."""
from __future__ import annotations

import json
import os
import subprocess
import sys


def run(ws, *args):
    env = {**os.environ, "KONSTANT_HOME": str(ws)}
    env.pop("KONSTANT_CATALOG", None)
    return subprocess.run([sys.executable, "-m", "konstant", "agents", *args], env=env,
                          capture_output=True, text=True, timeout=120)


def test_agents_list_json(workspace):
    r = run(workspace, "list", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert len(data["types"]) == 10 and len(data["agents"]) == 12   # + intake, planner, scenario writer
    assert len(data["skills"]) == 26 and len(data["workflows"]) == 10 and data["bijection"]
    assert data["types"]["code"] == {"agent": "coder", "deliverable": "build",
                                     "workflow": "workflow-code",
                                     "skills": data["types"]["code"]["skills"]}


def test_sync_check_exit_codes(workspace):
    assert run(workspace, "sync", "--check").returncode == 1          # nothing generated yet
    r = run(workspace, "sync")
    assert r.returncode == 0 and "change(s)" in r.stdout
    assert run(workspace, "sync", "--check").returncode == 0
    f = workspace / "AGENTS.md"
    f.write_text(f.read_text() + "edited\n")
    r = run(workspace, "sync", "--check")
    assert r.returncode == 1 and "drifted: AGENTS.md" in r.stdout
    assert run(workspace, "sync").returncode == 0 and run(workspace, "sync", "--check").returncode == 0


def test_a_bad_permissions_rule_in_konstant_toml_fails_the_sync(workspace):
    (workspace / "konstant.toml").write_text('[permissions]\nallow = ["Bash"]\n')
    r = run(workspace, "sync")
    assert r.returncode == 1 and "whole tool" in r.stdout
    assert not (workspace / ".claude").exists()
