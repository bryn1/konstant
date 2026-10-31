"""The konstant-gate dsh plugin and the dsh session surfaces.

- the vendored bundle is present and CURRENT (its header names the sha256 of index.ts; with
  esbuild available, `build.mjs --check` rebuilds it byte for byte);
- the node:test suite of the plugin passes (tests/harness/dsh_gate/plugin.test.mjs);
- `agents sync` writes the plugin, the session patch (config from konstant.toml) and the agent
  profiles for dsh, and only for dsh;
- the CLI the plugin calls: `task gate --json --harness dsh --cwd` (project from the cwd, the
  `[job:N]` tag, `--file-job --session` filing + reuse, a brief without a DoD refused) and
  `task close` (refused unless MET; MET -> claim when queued -> close -> verify);
- `konstant dsh --dry-run`: both patches, the relocated session home, the session directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from konstant import catalog
from konstant.agents.generate import HEADER, Generator
from konstant.harnesses import dsh_session
from tests.cli.conftest import Workspace
from tests.harness.conftest import golden, hcfg, norm

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "konstant" / "harnesses" / "dsh_gate"
CAT = catalog.load()
FAKE = REPO / "tests" / "fixtures" / "fake_harness.py"


def _node():
    exe = shutil.which("node")
    if not exe:
        return None
    v = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip()
    try:
        return exe if int(v.lstrip("v").split(".")[0]) >= 20 else None
    except ValueError:
        return None


def test_bundle_present_and_built_from_the_current_source():
    assert dsh_session.BUNDLE.is_file(), "konstant-gate.mjs (the vendored build) is missing"
    have = dsh_session.bundle_source_sha()
    want = hashlib.sha256((SRC / "index.ts").read_bytes()).hexdigest()
    assert have == want, ("konstant-gate.mjs was not built from the current index.ts: run "
                          "`node src/konstant/harnesses/dsh_gate/build.mjs`")
    text = dsh_session.bundle_text()
    assert "@deepseek-ai/" not in text.split("\n", 1)[1], "the bundle must import no dsh package"
    assert "export {" in text and "apply" in text


def test_bundle_check_detects_a_stale_build(tmp_path):
    """The other side of the test above: an edited source no longer matches the bundle's sha."""
    src = tmp_path / "index.ts"
    src.write_bytes((SRC / "index.ts").read_bytes() + b"\n// edited\n")
    assert hashlib.sha256(src.read_bytes()).hexdigest() != dsh_session.bundle_source_sha()


def _esbuild_env():
    env = dict(os.environ)
    if env.get("ESBUILD") or shutil.which("esbuild"):
        return env
    src = env.get("DSH_SOURCE", "")
    return env if src and (Path(src) / "node_modules" / ".bin" / "esbuild").exists() else None


@pytest.mark.skipif(_node() is None or _esbuild_env() is None,
                    reason="node >= 20 and esbuild (ESBUILD, PATH or DSH_SOURCE) needed to rebuild")
def test_bundle_rebuilds_byte_for_byte():
    r = subprocess.run([_node(), str(SRC / "build.mjs"), "--check"], capture_output=True,
                       text=True, env=_esbuild_env(), timeout=300)
    assert r.returncode == 0, r.stderr + r.stdout


@pytest.mark.skipif(_node() is None, reason="node >= 20 not on PATH")
def test_plugin_node_suite():
    r = subprocess.run([_node(), "--test", str(REPO / "tests" / "harness" / "dsh_gate")],
                       capture_output=True, text=True, timeout=300, cwd=str(REPO))
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert "# fail 0" in r.stdout and "# pass " in r.stdout


def _gen(ws, gate=None, policy=None, **h):
    return Generator(CAT, ws, {"allow": [], "sandbox": True}, python="/py/bin/python",
                     harness=hcfg(**h), gate=gate, policy=policy)


def test_sync_writes_the_session_surfaces_for_dsh_only(ws, home):
    files = _gen(ws, gate={"max_resumes": 2, "verify_after_close": True, "file_job": True},
                 policy={"max_rounds": 4}, name="dsh").render()
    assert files[".dsh/konstant-gate.mjs"] == f"// {HEADER}\n" + dsh_session.bundle_text()
    patch = files[".dsh/konstant-session.patch.yml"]
    golden("dsh-konstant-session.patch.yml", norm(patch, ws))
    assert f'name: "{ws}/.dsh/konstant-gate.mjs"' in patch
    for line in (f'konstant: "{ws}/bin/konstant"', "maxResumes: 2", "maxVerifyRounds: 4",
                 "verify: true", "fileJob: true"):
        assert line in patch, line
    agents = sorted(p for p in files if p.startswith(".dsh/agents/"))
    assert agents == sorted(f".dsh/agents/{a}.md" for a in CAT.agents())
    assert HEADER in files[".dsh/agents/coder.md"]
    claude = _gen(ws).render()
    assert not any(p.startswith(".dsh/") for p in claude)


def test_sync_check_and_stale_removal_cover_the_session_files(ws, home):
    g = _gen(ws, name="dsh")
    g.sync()
    (ws / ".dsh" / "konstant-gate.mjs").write_text("// tampered\n" + HEADER + "\n")
    assert "drifted: .dsh/konstant-gate.mjs" in g.check()
    g.sync()
    assert g.check() == []
    g2 = _gen(ws, name="codex")
    stale = set(g2.check())
    assert {"stale: .dsh/konstant-gate.mjs", "stale: .dsh/konstant-session.patch.yml",
            "stale: .dsh/agents/coder.md"} <= stale
    g2.sync()
    assert not (ws / ".dsh").exists()


# --- the CLI the plugin calls -------------------------------------------------------------------

@pytest.fixture(scope="module")
def bws(tmp_path_factory):
    w = Workspace(tmp_path_factory.mktemp("dshws"))
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n')
    w.ok("board", "init")
    w.ok("board", "start")
    w.ok("project", "add", "demo", "--init-git")
    yield w
    w.run("board", "stop")


def _gate(w, text, *extra, cwd=None):
    cwd = cwd or w.home / "projects" / "demo"
    return w.run("task", "gate", "--json", "--harness", "dsh", "--cwd", str(cwd), *extra, "-",
                 stdin=text)


def test_gate_json_binds_a_job_tag_and_finds_the_project_from_the_cwd(bws):
    brief = bws.write("b.md", "Write USAGE.md.\n\nDoD:\n- USAGE.md exists\n"
                      "PROBE: test -f projects/demo/USAGE.md => ^ok$\n")
    jid = json.loads(bws.ok("job", "add", "T1: usage doc", "--project", "demo", "--type",
                            "docs", "--brief", str(brief), "--json").stdout)["id"]
    sub = bws.home / "projects" / "demo" / "docs"
    sub.mkdir(exist_ok=True)
    res = _gate(bws, f"[job:{jid}] [type:docs] write USAGE.md for the demo", cwd=sub)
    assert res.returncode == 0, res.stderr
    g = json.loads(res.stdout)
    assert g["type"] == "docs" and g["job"] == jid
    assert g["project"] == str((bws.home / "projects" / "demo").resolve())
    assert ".dsh/agents/<agent>.md" in g["block"] and "DoD-1 | USAGE.md exists" in g["block"]
    rec = json.loads((Path(g["run_dir"]) / "record.json").read_text())
    assert rec["job"] == jid and rec["job_bound_by"] == "tag"
    small = json.loads(_gate(bws, "what is the board?").stdout)
    assert small["type"] == "small"


def test_file_job_files_claims_binds_and_reuses_per_session(bws):
    text = "[type:docs] write CHANGES.md\n\nDoD:\n- CHANGES.md lists the release\n"
    a = _gate(bws, text, "--file-job", "--session", "s-1")
    assert a.returncode == 0, a.stderr
    jid = json.loads(a.stdout)["job"]
    job = json.loads(bws.ok("job", "show", str(jid), "--json").stdout)
    assert job["status"] == "claimed" and job["type"] == "docs" and job["project"] == "demo"
    bound = json.loads((bws.home / "var" / "sessions.json").read_text())
    assert bound["s-1"]["job"] == str(jid)
    b = json.loads(_gate(bws, "[type:docs] also add a heading", "--file-job", "--session",
                         "s-1").stdout)
    assert b["job"] == jid                                   # the open job is reused
    c = _gate(bws, "[type:docs] write NOTES.md without a definition of done", "--file-job",
              "--session", "s-2")
    assert c.returncode != 0 and "DoD" in c.stderr           # the board refuses an empty promise


def test_task_close_refuses_unless_met(bws):
    g = json.loads(_gate(bws, "[type:docs] write X.md").stdout)
    res = bws.run("task", "close", "--json", g["run_dir"])
    assert res.returncode == 3, res.stderr
    out = json.loads(res.stdout)
    assert out["check"] == 3 and out["verdict"] is None and out["reasons"]


def test_task_close_claims_closes_and_verifies_a_met_run(bws):
    """A MET run whose job a verify FAIL sent back (here: reopened) is claimed, closed, verified."""
    brief = bws.write("c.md", "Add greet().\n\nDoD:\n- greet.py exists\n"
                      "PROBE: test -f projects/demo/greet.py => ^ok$\n")
    jid = json.loads(bws.ok("job", "add", "T9: greet", "--project", "demo", "--type", "code",
                            "--brief", str(brief), "--json").stdout)["id"]
    toml = bws.home / "konstant.toml"
    saved = toml.read_text()
    toml.write_text(saved + "[gate]\nverify_after_close = false\n")
    try:
        res = bws.run("task", "run", "[type:code] add greet()", "--job", str(jid), "--harness",
                      f"{sys.executable} {FAKE} {{prompt_file}}")
        assert res.returncode == 0, res.stderr[-2000:]
    finally:
        toml.write_text(saved)
    run = next(d for d in (bws.home / "var" / "runs").iterdir()
               if json.loads((d / "record.json").read_text()).get("job") == jid)
    assert json.loads(bws.ok("job", "show", str(jid), "--json").stdout)["status"] == \
        "completed_unverified"
    bws.ok("job", "reopen", str(jid), "verify FAIL stand-in")
    out = bws.run("task", "close", "--json", str(run))
    assert out.returncode == 0, out.stdout + out.stderr
    data = json.loads(out.stdout)
    assert data["verdict"] == "PASS" and data["status"] == "verified" and data["job"] == jid


def test_konstant_dsh_dry_run(bws):
    bws.ok("agents", "sync")
    res = bws.run("dsh", "--dry-run", "web", "--port", "3999")
    assert res.returncode == 0, res.stderr
    d = json.loads(res.stdout)
    ws = str(bws.home)
    assert d["argv"][1:] == ["--profile", "web", "--patch", f"{ws}/.dsh/konstant.patch.yml",
                             "--patch", f"{ws}/.dsh/konstant-session.patch.yml", "--port", "3999"]
    assert d["env"]["DSH_HOME"] == f"{ws}/var/harness/dsh/session/home"
    assert d["env"]["KONSTANT_HOME"] == ws and d["cwd"] == str(Path(ws).resolve())
    proj = json.loads(bws.ok("dsh", "--dry-run", "--project", "demo", "headless").stdout)
    assert proj["cwd"] == str((bws.home / "projects" / "demo").resolve())


def test_konstant_dsh_needs_the_synced_session_files(tmp_path):
    w = Workspace(tmp_path)
    w.ok("board", "init")
    res = w.run("dsh", "--dry-run", "web")
    assert res.returncode == 2 and "agents sync" in res.stderr
