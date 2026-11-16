"""Rules `tests` (+ the traced `exercise` leg).

tests: the test command passes. `[gate] test_cmd` comes from the WORKSPACE's konstant.toml (never
       from the run record, which a phase could forge; REVIEW F-06). `auto` (default) = pytest from
       OUT when OUT holds test_*.py, AND pytest over the project when the project holds test files
       outside OUT (REVIEW F-18: a change that breaks an untouched test is UNMET); any other value
       is split with shlex (never a shell) and run in the project dir (OUT when there is none).
Every run of agent-written code goes through konstant.jail (bubblewrap when it works: read-only
root, writes only to OUT, the project and a private TMPDIR, tokens and credentials masked, no
network; `[gate] jail = false` turns it off).
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys

from konstant import jail
from konstant.gate.rules import exercise
from konstant.gate.rules.common import CACHE_DIRS, RUN_DIRS, Finding, Run

TIMEOUT_S = 900
SKIP_DIRS = CACHE_DIRS | RUN_DIRS | {"node_modules", "vendor", "third_party", "dist", "build",
                                     "site-packages"}


def has_tests(out) -> bool:
    for root, dirs, files in os.walk(out):
        dirs[:] = [d for d in dirs if d not in CACHE_DIRS and d not in RUN_DIRS]
        if any(f.startswith("test_") and f.endswith(".py") for f in files):
            return True
    return False


def project_has_tests(project, out) -> bool:
    """A Python test file in the project outside OUT, hidden dirs and vendored trees."""
    real_out = os.path.realpath(str(out))
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                   and os.path.realpath(os.path.join(root, d)) != real_out]
        if any((f.startswith("test_") or f.endswith("_test.py")) and f.endswith(".py")
               for f in files):
            return True
    return False


def pytest_argv(paths) -> list:
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *map(str, paths)]


def run_cmd(argv, cwd, env=None, jail_rw=(), run: Run | None = None):
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("PYTEST_", "KONSTANT_EXERCISE"))}
    full_env = {**clean, "PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    enabled = bool(run.gate.get("jail", True)) if run is not None else True
    home = run.workspace if run is not None else None
    rw = (cwd, *jail_rw)
    try:
        with jail.session(argv, rw=rw, home=home, cwd=cwd, net=False, env=full_env,
                          enabled=enabled) as (cmd, run_env):
            r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                               timeout=TIMEOUT_S, env=run_env, stdin=subprocess.DEVNULL,
                               errors="replace")
    except subprocess.TimeoutExpired:
        return "timeout", ""
    except OSError as exc:
        return f"could not run ({exc})", ""
    return r.returncode, (r.stdout + r.stderr)[-600:]


def _last(tail: str) -> str:
    """The first `FAILED <test>` line of a pytest tail, else its last line."""
    lines = tail.strip().splitlines()
    return next((ln for ln in lines if ln.startswith("FAILED ")), lines[-1] if lines else "")


def check(run: Run) -> list:
    cmd = run.gate.get("test_cmd", "auto")
    out, project = run.out, run.project
    rw = [str(out)] + ([str(project)] if project and project.is_dir() else [])
    if cmd != "auto":
        cwd = project if project and project.is_dir() else out
        rc, tail = run_cmd(shlex.split(cmd), cwd, jail_rw=rw, run=run)
        return [] if rc == 0 else [Finding("tests", f"test command `{cmd}` failed in {cwd} "
                                                    f"(exit {rc}): {tail.strip()[-200:]}",
                                           owner="producer")]
    found = []
    if project and project.is_dir() and project_has_tests(project, out):
        rc, tail = run_cmd(pytest_argv(["--rootdir", project, project]), project, jail_rw=rw,
                           run=run)
        if rc not in (0, 5):                    # 5 = pytest collected nothing: nothing broke
            found.append(Finding("tests", f"the project's own test suite fails in {project} "
                                          f"(exit {rc}): {_last(tail)}", owner="producer"))
    if not out.is_dir() or not has_tests(out):
        return found
    # each scoped verifier's private dir OUT/verify-<stem>/ is its own pytest session, owned by
    # that verifier: the producer cannot write it, so a failure there is never the producer's
    # to fix (live run L5-L: a tester's mutation copies collided there and the producer was
    # resumed on them); the rest of OUT is the producer's, as before; one trace covers both
    from konstant.gate.rules.judged import own_dir
    private = {own_dir(v): v for v in run.rec.get("own_dirs") or []}
    ignore = [a for d in sorted(private) if (out / d).is_dir() for a in ("--ignore", out / d)]
    env, tmp = None, None
    if run.rec.get("exercise"):
        env, tmp, rec = exercise.traced_env(str(out))
    try:
        jrw = rw + ([tmp] if tmp else [])
        for d, vf in sorted(private.items()):
            if (out / d).is_dir() and has_tests(out / d):
                rc, tail = run_cmd(pytest_argv(["--rootdir", out / d, out / d]), out, env,
                                   jail_rw=jrw, run=run)
                if rc not in (0, 5):
                    found.append(Finding("tests", f"pytest failed in {out / d} (exit {rc}): "
                                                  f"{_last(tail)}", owner=f"verifier:{vf}"))
        rc, tail = run_cmd(pytest_argv(["--rootdir", out, *ignore, out]), out, env,
                           jail_rw=jrw, run=run)
        if rc != 0 and not (rc == 5 and ignore):     # 5: every test lies in a private dir
            return found + [Finding("tests", f"pytest failed in {out} (exit {rc}): {_last(tail)}",
                                    owner="producer")]
        if tmp is None:
            return found
        return found + [Finding("exercise", f"tests under {out} never call into {c} - add a "
                                            "test that exercises it", owner="producer")
                        for c in exercise.unexercised(str(out), rec)]
    finally:
        if tmp:
            exercise.cleanup(tmp)
