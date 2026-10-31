"""Re-run a verify command (DESIGN §7 step 4): the DoD's VERIFY_CMD, or the closer's verify_cmd
in procedural mode (verifier.rerun_command decides which).

The command runs with a scrubbed environment (no KONSTANT_*, no token-like variables), in its own
process group that is killed on timeout, and inside konstant.jail when it works: the workspace's
var/secrets/ and the usual credential dirs masked, writes only to the project dir, an own pid
namespace. Without the jail it runs as the invoking user with that user's full reach (a documented
limit). If the evidence names a commit it must be an ancestor of the project's HEAD, else the
re-run FAILS.
Result keys: ran, skipped, cmd, source, exit, output, timed_out, commit, commit_ok, ok, jailed
(ok: True pass, False fail, None unverifiable - the command was not run or timed out).
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path

from konstant import jail as jail_mod
from konstant.gate.rules.common import GIT_ISOLATION
from konstant.verify.procenv import git_env, scrub_env

OUTPUT_KEEP = 4000
_COMMIT = re.compile(r"(?!-)[0-9A-Za-z._/-]{1,200}")


def _result(**kw) -> dict:
    base = {"ran": False, "skipped": None, "cmd": None, "source": None, "exit": None,
            "output": "", "timed_out": False, "commit": None, "commit_ok": None, "ok": None,
            "jailed": False}
    base.update(kw)
    return base


def skipped(reason: str, source=None) -> dict:
    return _result(skipped=reason, source=source)


def commit_reachable(tree: Path, commit: str, timeout: float = 30) -> tuple:
    """(ok, detail): is `commit` an ancestor of (or equal to) the tree's HEAD."""
    if not _COMMIT.fullmatch(commit):
        return False, f"evidence commit {commit!r} is not a plain revision"
    try:
        proc = subprocess.run(["git", *GIT_ISOLATION, "-C", str(tree), "merge-base",
                               "--is-ancestor", commit, "HEAD"], capture_output=True, text=True,
                              env=git_env(),
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not check commit {commit}: {exc}"
    if proc.returncode == 0:
        return True, ""
    if proc.returncode == 1:
        return False, f"commit {commit} is not an ancestor of the project HEAD"
    return False, f"commit {commit} cannot be checked against HEAD: {proc.stderr.strip()[:200]}"


def _run_group(cmd: str, cwd: Path, timeout: float, home=None, jail: bool = True) -> tuple:
    """(exit, output, timed_out, jailed): sh -c in a fresh process group, killed whole on timeout."""
    with jail_mod.session(["/bin/sh", "-c", cmd], rw=(cwd,), home=home, cwd=cwd, net=True,
                          env=scrub_env(), enabled=jail) as (argv, env):
        jailed = argv[0] != "/bin/sh"
        return (*_run_argv(argv, cwd, env, timeout), jailed)


def _run_argv(argv, cwd: Path, env: dict, timeout: float) -> tuple:
    proc = subprocess.Popen(argv, cwd=str(cwd), env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    timed_out = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, _ = proc.communicate()
    text = (out or b"").decode("utf-8", "replace")
    return proc.returncode, text[-OUTPUT_KEEP:], timed_out


def rerun(evidence: dict | None, project_dir: Path | None, timeout: float = 900, *,
          source: str = "closer", home=None, jail: bool = True) -> dict:
    ev = evidence or {}
    cmd = (ev.get("verify_cmd") or "").strip()
    if not cmd:
        return _result(skipped="the evidence has no verify_cmd", source=source)
    if project_dir is None or not Path(project_dir).is_dir():
        return _result(skipped="the project has no directory to run in", cmd=cmd, source=source)
    res = _result(cmd=cmd, source=source)
    commit = (ev.get("commit") or "").strip()
    if commit:
        ok, detail = commit_reachable(Path(project_dir), commit)
        res.update(commit=commit, commit_ok=ok)
        if not ok:
            res.update(ok=False, skipped=detail)
            return res
    code, out, timed_out, jailed = _run_group(cmd, Path(project_dir), timeout, home, jail)
    res.update(ran=True, exit=code, output=out, timed_out=timed_out, jailed=jailed)
    if timed_out:
        res["skipped"] = f"timeout after {timeout}s"
    else:
        res["ok"] = code == 0
    return res
