"""A harness installed under $HOME starts inside every jail, $HOME masked (L5-6 live finding 1).

The live run's dsh was a two-line `sh` launcher in a directory under $HOME that runs a runtime
(node) and the harness's entry script (dsh's bin.js inside a pnpm monorepo), both under $HOME. The
web researcher's jail masks $HOME (home_read = false), and the dsh adapter's confine() built its
jail without the program's roots: `bwrap: execvp dsh: No such file or directory`. On CI the same
class hit the command adapter: the fake harness `python <repo>/tests/fixtures/fake_harness.py`
lies under the runner's $HOME and only argv[0]'s directories were kept.

Here the same shapes are laid out under a HOME-like directory: a launcher, a runtime, an entry
script inside a package whose shared dependency lives at the package root, plus files the phase
must never read (a key under ~/.ssh, a private note). Green: the program starts and reads its own
dependency; the key and the note stay masked. Red twin: the same jail without the kept roots
cannot start the launcher (the exact live error)."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from konstant import jail
from konstant.confinement import CLOSED
from konstant.harnesses import base, dsh
from konstant.harnesses.base import Phase, jail_layout
from tests.harness.conftest import values

needs_jail = pytest.mark.skipif(not jail.available(), reason="bubblewrap cannot run here")

ENTRY = r'''
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
dep = os.path.join(here, "..", "..", "..", "node_modules", "dep", "data.txt")
print("HARNESS-OK", open(dep).read().strip())
for name in sys.argv[1:]:
    try:
        open(name).read()
        print("READ", name)
    except OSError:
        print("MASKED", name)
'''


@pytest.fixture()
def installed(home, monkeypatch):
    """The live layout, under HOME: ~/rt/bin/py (the runtime), ~/opt/harness (a package with
    package.json and node_modules at its root; the entry script in apps/cli/lib), ~/kit/bin/dsh
    (the launcher) and the secrets the jail must keep masked."""
    rt = home / "rt" / "bin"
    rt.mkdir(parents=True)
    (rt / "py").symlink_to(sys.executable)
    pkg = home / "opt" / "harness"
    (pkg / "apps" / "cli" / "lib").mkdir(parents=True)
    (pkg / "node_modules" / "dep").mkdir(parents=True)
    (pkg / "package.json").write_text("{}\n")
    (pkg / "apps" / "cli" / "package.json").write_text("{}\n")
    (pkg / "node_modules" / "dep" / "data.txt").write_text("dep-loaded\n")
    entry = pkg / "apps" / "cli" / "lib" / "bin.py"
    entry.write_text(ENTRY)
    kit = home / "kit" / "bin"
    kit.mkdir(parents=True)
    launcher = kit / "dsh"
    launcher.write_text(f"#!/bin/sh\nexec {rt / 'py'} {entry} \"$@\"\n")
    launcher.chmod(0o755)
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_ed25519").write_text("KEY\n")
    (home / "notes").mkdir()
    (home / "notes" / "private.txt").write_text("PRIVATE\n")
    path = f"{kit}:/usr/local/bin:/usr/bin:/bin"
    monkeypatch.setenv("PATH", path)
    return {"home": home, "entry": entry, "launcher": launcher, "rt": rt / "py", "path": path,
            "secrets": [str(home / ".ssh" / "id_ed25519"), str(home / "notes" / "private.txt")]}


def researcher(ws):
    ph = Phase({**values(ws), "out": None}, wconf=CLOSED, identity="researcher")
    assert ph.conf.home_read is False
    return ph


def start(argv, inst, ws):
    env = {"PATH": inst["path"], "HOME": str(inst["home"]), "LANG": "C.UTF-8"}
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, env=env,
                          cwd=str(ws), stdin=subprocess.DEVNULL)


def test_program_roots_follow_the_launcher_and_stop_below_home_green(installed):
    home = os.path.realpath(installed["home"])
    keep = base.program_roots(["dsh", "--profile", "headless", "-"])
    assert os.path.join(home, "kit", "bin") in keep                 # the launcher's directory
    assert os.path.join(home, "rt", "bin") in keep                  # the runtime it execs
    assert os.path.join(home, "opt", "harness") in keep             # the OUTERMOST package root
    assert home not in keep and not any(k in (home, os.path.join(home, ".ssh")) for k in keep)
    assert all(k.startswith(home + "/") for k in keep)


def test_program_roots_of_an_interpreter_and_its_script_green(installed, home):
    script = home / "tools" / "fake_harness.py"
    script.parent.mkdir()
    script.write_text("print('ok')\n")
    key = home / "tools" / "api.key"                        # a file the command names: no program
    key.write_text("k\n")
    keep = base.program_roots([sys.executable, str(script), f"--key={key}"])
    assert os.path.realpath(script.parent) in keep and os.path.realpath(key) not in keep
    loose = home / "harness.py"                              # a script directly in $HOME
    loose.write_text("print('ok')\n")
    keep = base.program_roots([sys.executable, str(loose)])
    assert os.path.realpath(loose) in keep and os.path.realpath(home) not in keep
    shim = home / "dsh-shim"                                 # a launcher directly in $HOME
    shim.write_text(installed["launcher"].read_text())
    shim.chmod(0o755)
    keep = base.program_roots([str(shim), "-"])
    assert os.path.realpath(shim) in keep and os.path.realpath(home) not in keep
    assert os.path.realpath(home / "opt" / "harness") in keep


@needs_jail
def test_a_runtime_prefix_under_home_keeps_its_library_dir_green(installed, ws):
    """A runtime installed as <prefix>/bin + <prefix>/lib under $HOME (a Python's stdlib, uv or
    pyenv style): the library dir stays reachable."""
    home = installed["home"]
    prefix = home / "pfx"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib").mkdir()
    (prefix / "lib" / "rt.txt").write_text("stdlib-here\n")
    run = prefix / "bin" / "run"
    run.write_text(f'#!/bin/sh\ncat "{prefix}/lib/rt.txt" && exec {sys.executable} "$@"\n')
    run.chmod(0o755)
    assert os.path.realpath(prefix / "lib") in base.program_roots([str(run)])
    argv = base.jailed([str(run), "-c", "print('ran')"], researcher(ws))
    r = start(argv, installed, ws)
    assert r.returncode == 0 and r.stdout.split() == ["stdlib-here", "ran"], (r.stdout, r.stderr)


@needs_jail
def test_dsh_launcher_under_home_starts_in_the_research_jail_green(installed, ws):
    ph = researcher(ws)
    argv = dsh.Dsh().confine(["dsh", *installed["secrets"]], ph)
    assert argv[0].endswith("bwrap")
    r = start(argv, installed, ws)
    assert r.returncode == 0, r.stderr
    assert "HARNESS-OK dep-loaded" in r.stdout
    for s in installed["secrets"]:
        assert f"MASKED {s}" in r.stdout, r.stdout


@needs_jail
def test_dsh_launcher_under_home_without_its_roots_cannot_start_red(installed, ws):
    """The red twin, the live error: the same jail, the program's roots not kept."""
    ph = researcher(ws)
    argv = jail.wrap(["dsh", *installed["secrets"]], **jail_layout(ph, tmpdir=False))
    r = start(argv, installed, ws)
    assert r.returncode != 0 and "execvp dsh" in r.stderr, (r.stdout, r.stderr)


@needs_jail
def test_interpreter_script_under_home_starts_in_the_research_jail_green(installed, ws):
    """The CI shape: `python <dir under $HOME>/harness.py` through the generic adapter path."""
    ph = researcher(ws)
    argv = base.jailed([str(installed["rt"]), str(installed["entry"]), *installed["secrets"]], ph)
    r = start(argv, installed, ws)
    assert r.returncode == 0 and "HARNESS-OK dep-loaded" in r.stdout, r.stderr
    for s in installed["secrets"]:
        assert f"MASKED {s}" in r.stdout


@needs_jail
def test_interpreter_script_under_home_without_its_roots_cannot_start_red(installed, ws):
    ph = researcher(ws)
    keep = base.exe_roots(str(installed["rt"]))          # argv[0] only: the pre-fix rule
    argv = jail.wrap([str(installed["rt"]), str(installed["entry"])],
                     **jail_layout(ph, keep=keep))
    r = start(argv, installed, ws)
    assert r.returncode != 0 and "can't open file" in r.stderr, (r.stdout, r.stderr)
