"""Second security review, G-01..G-05: konstant's machinery is one list that every adapter and the jail obey
(G-01, G-03), the jail masks the agent CLIs' homes (G-04), and the dsh layer check judges the
composed result and fails closed (G-02, G-05). Each test was written from the review's
reproduction and was red on the reviewed code; the `*_still_*` twins
hold before and after the fix. The dsh on PATH is tests/fixtures/stub_dsh.py (dsh's own layer rules, no model);
phases run through the real adapter: its argv, env, fresh home and jail."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from konstant import jail
from tests.cli.conftest import Workspace
from tests.fixtures import stub_dsh
from tests.harness.conftest import home  # noqa: F401  (an empty HOME fixture)

needs_jail = pytest.mark.skipif(not jail.available(), reason="bubblewrap cannot run here")
# the review's list of konstant machinery a phase may never write (G-01/G-03)
MACHINERY_DIRS = (".claude", ".dsh", ".agents", ".gemini", "var/harness", "catalog", ".git",
                  "var/secrets")
MACHINERY_FILES = ("AGENTS.md", "CLAUDE.md", "var/board.db")


@pytest.fixture()
def dws(tmp_path, home):
    """A workspace that mixes harnesses (dsh by default, claude for review): every
    generated surface exists, projects/demo is a git repo, the stub dsh is on PATH."""
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n'
                    '[harness.types.review]\nname = "claude"\n')
    w.ok("board", "init")
    w.ok("agents", "sync")
    proj = w.home / "projects" / "demo"
    proj.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-C", str(proj), "-c", "user.email=t@example.com", "-c",
                        "user.name=t", *args], check=True)
    for d in ("catalog", ".git"):
        (w.home / d).mkdir(exist_ok=True)
    w.bindir = tmp_path / "fakebin"
    w.bindir.mkdir()
    stub_dsh.install(w.bindir)
    w.log = w.home / "var" / "runs" / "r1" / "out" / "stub.log"   # writable inside the jail
    w.log.parent.mkdir(parents=True)
    return w


def session_home(ws: Path) -> Path:
    """The operator's `konstant dsh` session home (var/harness/dsh/session/ + home)."""
    return ws / "var" / "harness" / "dsh" / "session" / "home"


def env_of(w, **extra) -> dict:
    return w.env(PATH=f"{w.bindir}:{os.environ['PATH']}", STUB_DSH_LOG=str(w.log), **extra)


def records(w) -> list:
    return [json.loads(ln) for ln in w.log.read_text().splitlines()] if w.log.exists() else []


def phase(w, label: str, cwd=None, **extra) -> None:
    """One phase exactly as the runner starts it: HarnessSet -> the dsh adapter."""
    code = (
        "import json, sys\nfrom pathlib import Path\n"
        "from konstant.config import load\nfrom konstant.gate.harness import HarnessSet\n"
        f"ws = Path({str(w.home)!r})\ncfg = load(ws)\n"
        "hs = HarnessSet(cfg.data['harness'], ws, jail=bool(cfg.data['gate']['jail']))\n"
        "run = ws / 'var' / 'runs' / 'r1'\n(run / 'out').mkdir(parents=True, exist_ok=True)\n"
        f"cwd = Path({str(cwd or w.home / 'projects' / 'demo')!r})\n"
        f"r = hs.run('PROMPT', agent='coder', cwd=cwd, run_dir=run, label={label!r},\n"
        "           out=run / 'out')\nprint(r.rc)\n")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=env_of(w, **extra), timeout=120, cwd=str(w.home))
    assert res.returncode == 0, res.stderr


def outcomes(w) -> dict:
    return {r["act"].split(":", 1)[1]: r["result"] for r in records(w) if "act" in r}


# --- G-01 / G-03: no phase writes konstant's machinery ---------------------------------------

def _targets(w) -> dict:
    ws = w.home
    return {"session home": session_home(ws) / "profiles/web/cordis.patch.yml",
            "shared phase home": ws / "var/harness/dsh" / "home" / "profiles/headless/cordis.patch.yml",
            ".dsh plugin": ws / ".dsh/konstant-gate.mjs", ".agents": ws / ".agents/x.md",
            ".claude": ws / ".claude/x.md", "catalog": ws / "catalog/x.md",
            "AGENTS.md": ws / "AGENTS.md", "CLAUDE.md": ws / "CLAUDE.md",
            "var/harness": ws / "var/harness/x", "toml": ws / "konstant.toml",
            "project .git/config": ws / "projects/demo/.git/config"}


@needs_jail
def test_G01_a_dsh_phase_cannot_write_the_session_home_or_any_machinery(dws):
    t = _targets(dws)
    allowed = {"project file": dws.home / "projects/demo/ok.txt", "own home": "$DSH_HOME/x"}
    acts = ";".join(f"write:{p}" for p in [*t.values(), *allowed.values()])
    phase(dws, "02-coder", STUB_DSH_ACTIONS=acts)
    got = outcomes(dws)
    wrote = [name for name, p in t.items() if got.get(str(p)) == "WROTE"]
    assert not wrote, (wrote, got)
    assert got[str(allowed["project file"])] == "WROTE" and got["$DSH_HOME/x"] == "WROTE", got


@needs_jail
def test_G01_a_phase_in_the_workspace_root_cannot_write_machinery(dws):
    """A run without a project starts its phases in the workspace itself: the jail bound it all
    writable before the fix; machinery and var/ now stay read-only inside it."""
    t = _targets(dws)
    t["other run record"] = dws.home / "var/runs/old/record.json"
    (dws.home / "var/runs/old").mkdir(parents=True)
    acts = ";".join(f"write:{p}" for p in t.values()) + f";write:{dws.home / 'notes.md'}"
    phase(dws, "02-coder", cwd=dws.home, STUB_DSH_ACTIONS=acts)
    got = outcomes(dws)
    wrote = [name for name, p in t.items() if got.get(str(p)) == "WROTE"]
    assert not wrote, (wrote, got)
    assert got[str(dws.home / "notes.md")] == "WROTE", got        # the workspace itself: yes


def test_G01_a_layer_planted_by_one_phase_never_loads_into_a_later_phase(dws):
    """The phases' dsh home persisted across phases and runs: a producer's profile layer loaded
    into every later phase, verifiers included (the F-05 class without a process to reap)."""
    marker = dws.home / "projects" / "demo" / "PAYLOAD-RAN"
    payload = f"open({str(marker)!r}, 'a').write('x')"
    phase(dws, "02-coder", STUB_DSH_ACTIONS="plant:$DSH_HOME/profiles/headless/cordis.patch.yml",
          STUB_DSH_PAYLOAD=payload)
    assert outcomes(dws), records(dws)                  # the plant itself went into its own home
    phase(dws, "03-tester")
    runs = [r for r in records(dws) if "argv" in r]
    assert len(runs) == 2 and runs[0]["DSH_HOME"] != runs[1]["DSH_HOME"], runs
    assert not runs[1]["loaded"] and not marker.exists(), runs[1]
    phases_dir = dws.home / "var/harness/dsh/phases"
    assert not phases_dir.exists() or not list(phases_dir.iterdir())  # nothing persists


def start_session(w, **extra):
    return w.run("dsh", "web", "--port", "3999", env=env_of(w, **extra))


def test_G01_a_layer_in_the_session_home_refuses_konstant_dsh(dws):
    """Whoever planted it (an unsandboxed phase, an operator mistake): the unjailed session does
    not start on a layer that is not konstant's, even one inside the workspace."""
    layer = session_home(dws.home) / "profiles/web/cordis.patch.yml"
    layer.parent.mkdir(parents=True)
    layer.write_text("- insert:\n    - id: operator-plugin\n      name: file:///x/evil.mjs\n"
                     "# STUB-PAYLOAD: open('/dev/null')\n")
    res = start_session(dws)
    assert res.returncode == 1 and "refused" in res.stderr, res.stdout + res.stderr
    assert str(layer) in res.stderr
    assert not [r for r in records(dws) if "argv" in r], "the session started"


def test_G01_installed_packages_in_the_session_home_refuse_konstant_dsh(dws):
    nm = session_home(dws.home) / "profiles/web/node_modules/@deepseek-ai/dsh-base"
    nm.mkdir(parents=True)
    res = start_session(dws)
    assert res.returncode == 1 and "node_modules" in res.stderr, res.stdout + res.stderr


def test_G01_a_changed_session_plugin_refuses_konstant_dsh(dws):
    plugin = dws.home / ".dsh" / "konstant-gate.mjs"
    plugin.write_text(plugin.read_text() + "\n// planted\n")
    res = start_session(dws)
    assert res.returncode == 1 and ".dsh/konstant-gate.mjs" in res.stderr, res.stderr
    assert "agents sync" in res.stderr


def test_G01_konstant_dsh_still_starts_on_konstants_own_layers(dws):
    res = start_session(dws)
    assert res.returncode == 0 and "dsh started" in res.stdout, res.stdout + res.stderr


def test_G03_claude_settings_deny_every_machinery_path(dws):
    from konstant.agents import settings
    data = json.loads(settings.render(dws.home, {}))
    deny = data["permissions"]["deny"]
    ws = settings.abs_rule(dws.home)
    missing = [d for d in MACHINERY_DIRS if f"Edit({ws}/{d}/**)" not in deny]
    missing += [f for f in MACHINERY_FILES if f"Edit({ws}/{f})" not in deny]
    assert not missing, missing
    deny_write = data["sandbox"]["filesystem"]["denyWrite"]
    missing = [p for p in (*MACHINERY_DIRS, *MACHINERY_FILES)
               if str(dws.home / p) not in deny_write]
    assert not missing, missing


def test_G03_every_machinery_path_has_a_rule_in_every_adapter_and_the_jail(dws):
    """The class: konstant/machinery.py is the one list, and each consumer covers each entry."""
    import re

    from konstant import machinery
    from konstant.agents import settings
    from konstant.harnesses import codex, gemini
    from konstant.harnesses.base import Phase
    assert set(MACHINERY_DIRS) <= set(machinery.DIRS)
    assert set(MACHINERY_FILES) <= set(machinery.FILES)
    deny = json.loads(settings.render(dws.home, {}))["permissions"]["deny"]
    ws = settings.abs_rule(dws.home)
    for d in machinery.DIRS:
        assert f"Edit({ws}/{d}/**)" in deny, d
        (dws.home / d).mkdir(parents=True, exist_ok=True)
    for f in machinery.FILES:
        assert f"Edit({ws}/{f})" in deny, f
        (dws.home / f).touch()
    run = dws.home / "var/runs/r1"
    ph = Phase({"workspace": dws.home, "cwd": dws.home / "projects/demo", "run_dir": run})
    fs = codex.filesystem(ph)
    for p in (*machinery.DIRS, *machinery.FILES):
        # "deny" (a sealed path: memory/) is neither readable nor writable: covered too
        covered = (fs.get(f"{dws.home / p}/**") in ("read", "deny")
                   or fs.get(str(dws.home / p)) == "read"
                   or (p.startswith("var") and fs.get(f"{dws.home / 'var'}/**") == "read"))
        assert covered, p
    pol = gemini.policy(dws.home, [], "h")
    pattern = re.search(r'argsPattern = "(.*)"\ndecision = "deny"', pol).group(1)
    rx = re.compile(json.loads(f'"{pattern}"'))
    for p in (*machinery.DIRS, *machinery.FILES):
        probe = f'"file_path":"{dws.home / p}' + ("/x" if p in machinery.DIRS else '"')
        assert rx.search(probe), p
    argv = jail.wrap(["true"], rw=[dws.home], home=dws.home)
    if jail.available():
        bound_ro = {argv[i + 1] for i, a in enumerate(argv) if a == "--ro-bind"}
        for p in (*machinery.DIRS, *machinery.FILES):
            q = os.path.realpath(dws.home / p)
            assert q in bound_ro or os.path.realpath(dws.home / "var") in bound_ro and \
                p.startswith("var"), p


# --- G-04: the jail masks the agent CLIs' homes -----------------------------------------------

CRED = (".dsh", ".codex", ".gemini", ".claude", ".config/gh", ".ssh", ".aws")


@needs_jail
def test_G04_the_jail_masks_the_harness_credential_homes(tmp_path, home, monkeypatch):
    for d in CRED:
        (home / d).mkdir(parents=True)
        (home / d / "secret").write_text("S3CRET\n")
    (home / ".netrc").write_text("machine x password S3CRET\n")
    (home / "notes.txt").write_text("plain\n")
    elsewhere = tmp_path / "relocated-dsh-home"
    elsewhere.mkdir()
    (elsewhere / "secret").write_text("S3CRET\n")
    monkeypatch.setenv("DSH_HOME", str(elsewhere))
    ws = tmp_path / "ws"
    (ws / "var" / "secrets").mkdir(parents=True)
    seen = {}
    for p in [*(home / d / "secret" for d in CRED), home / ".netrc", elsewhere / "secret",
              home / "notes.txt"]:
        try:
            argv = jail.wrap(["cat", str(p)], rw=[ws], hide=jail.hidden(ws), home=ws, cwd=ws)
        except TypeError:                   # before the fix wrap() had no home= (the red run)
            argv = jail.wrap(["cat", str(p)], rw=[ws], hide=jail.hidden(ws), cwd=ws)
        r = subprocess.run(argv, capture_output=True, text=True)
        seen[str(p.relative_to(tmp_path))] = "READ" if "S3CRET" in r.stdout or "plain" in \
            r.stdout else "masked"
    readable = [k for k, v in seen.items() if v == "READ" and "notes.txt" not in k]
    assert not readable, seen
    assert seen["home/notes.txt"] == "READ", seen           # documented: other files stay readable


def test_G04_codex_and_claude_deny_the_same_credential_homes(tmp_path, home):
    from konstant.agents import settings
    from konstant.harnesses import codex
    from konstant.harnesses.base import Phase
    for d in (".dsh", ".gemini", ".claude", ".codex"):
        (home / d).mkdir()
    (home / ".codex" / "auth.json").write_text("{}")
    ws = tmp_path / "ws"
    (ws / "var" / "runs" / "r1").mkdir(parents=True)
    fs = codex.filesystem(Phase({"workspace": ws, "cwd": ws, "run_dir": ws / "var/runs/r1"}))
    assert {fs.get("~/.dsh"), fs.get("~/.gemini"), fs.get("~/.claude")} == {"deny"}, fs
    assert fs.get("~/.codex/auth.json") == "deny"
    deny_read = json.loads(settings.render(ws, {}))["sandbox"]["filesystem"]["denyRead"]
    for c in ("~/.dsh", "~/.codex", "~/.gemini", "~/.claude/.credentials.json"):
        assert c in deny_read, (c, deny_read)


def test_G04_docs_list_exactly_what_the_jail_masks():
    """Docs and doctor claim only what is proven: CONCEPTS names every masked location."""
    from konstant import machinery
    text = (Path(__file__).resolve().parents[2] / "docs" / "CONCEPTS.md").read_text()
    missing = [c for c in machinery.CREDENTIALS if f"`{c}`" not in text]
    assert not missing, missing
    assert "other files in your home stay readable" in text


# --- G-02 / G-05: the layer check judges the composed result, fail closed --------------------

def doctor_layers(w, **extra) -> dict:
    res = w.run("--json", "doctor", env=env_of(w, **extra))
    return {r["check"]: r for r in json.loads(res.stdout)["checks"]}["dsh layers"]


def forced_home(tmp_path, profile: str, body: str) -> Path:
    op = tmp_path / "operator-home"
    (op / "profiles" / profile).mkdir(parents=True, exist_ok=True)
    (op / "profiles" / profile / "cordis.patch.yml").write_text(body)
    return op


INSERT = "- insert:\n    - id: operator-plugin\n      name: file:///x/evil.mjs\n"


def test_G02_an_insert_only_foreign_layer_fails_doctor_and_refuses_the_session(dws, tmp_path):
    op = forced_home(tmp_path, "headless", INSERT)
    forced_home(tmp_path, "web", INSERT)
    knobs = {"STUB_DSH_DUMP": "forced", "STUB_DSH_FORCED_HOME": str(op)}
    row = doctor_layers(dws, **knobs)
    assert row["status"] == "FAIL" and str(op) in row["detail"], row
    res = start_session(dws, **knobs)
    assert res.returncode == 1 and "refused" in res.stderr and str(op) in res.stderr, res.stderr


def test_G02_a_bundle_added_to_the_session_profile_refuses_the_session(dws):
    prof = session_home(dws.home) / "profiles/web"
    prof.mkdir(parents=True)
    (prof / "package.json").write_text(json.dumps({"dsh": {"profile": {"bundles": [
        "@deepseek-ai/dsh-base", "@deepseek-ai/dsh-" + "web", "evil-bundle"]}}}))
    res = start_session(dws)
    assert res.returncode == 1 and "evil-bundle" in res.stderr, res.stdout + res.stderr


def test_G02_konstants_own_layers_still_pass_doctor(dws):
    row = doctor_layers(dws)
    assert row["status"] == "PASS", row


@pytest.mark.parametrize("mode", ["empty", "fail"])
def test_G05_an_unreadable_composition_fails_closed(dws, mode):
    """dsh on Node 20 exits 0 with no output: doctor said PASS and the session started."""
    row = doctor_layers(dws, STUB_DSH_DUMP=mode)
    assert row["status"] == "FAIL", row
    res = start_session(dws, STUB_DSH_DUMP=mode)
    assert res.returncode == 1 and "refused" in res.stderr, res.stdout + res.stderr
    if mode == "empty":
        assert "Node.js >= 22" in row["detail"]


def test_G05_a_run_does_not_start_dsh_phases_on_an_unreadable_composition(dws):
    res = subprocess.run([sys.executable, "-m", "konstant", "task", "run",
                          "[type:code] add greet()", "--project", "demo", "--harness", "dsh"],
                         capture_output=True, text=True, timeout=300, cwd=str(dws.home),
                         env=env_of(dws, STUB_DSH_DUMP="empty"))
    assert res.returncode != 0
    assert "could not read the composition" in res.stderr, res.stderr[-1500:]
    assert not [r for r in records(dws) if "argv" in r], "a dsh phase was started"


def test_G02_every_origin_form_of_the_dump_is_parsed():
    """dsh 0.2.1 renders `# == <origin>` and `# == <origin>, patched by A, B` (app-boot's
    renderConfigDump joins the patchers with ', '); the reviewed code read only `patched by (/path)`."""
    from konstant.harnesses.dsh import origins
    dump = ("# == @deepseek-ai/dsh-base\n- id: x\n"
            "# == @deepseek-ai/dsh-base, patched by @deepseek-ai/dsh-headless, /w/.dsh/k.yml\n"
            "# == /op/profiles/web/cordis.patch.yml\n- id: y\n")
    assert origins(dump) == ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless", "/w/.dsh/k.yml",
                             "/op/profiles/web/cordis.patch.yml"]
