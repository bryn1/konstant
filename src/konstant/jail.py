"""Run code an agent wrote (a project's tests, a verifier re-run) inside bubblewrap when it works.

The jail: the root file system read-only; writes only to the directories the caller names plus a
private TMPDIR; the workspace's `var/secrets/` and the usual credential locations under $HOME
masked; an own pid namespace with --die-with-parent (nothing the command starts outlives it);
optionally no network (`net=False`: only a private loopback). It is the same boundary Claude
Code's Linux sandbox draws (bubblewrap), so a command konstant runs for a sandboxed phase - an
excluded `task check` - stays inside that boundary (REVIEW F-06). Without a working `bwrap`
(macOS, user namespaces disabled) the command runs unjailed: `konstant doctor` reports which;
docs/CONCEPTS.md "Security model and limits" states what that means. KONSTANT_NO_JAIL=1 or
`[gate] jail = false` turns it off.

The bind rules read konstant/machinery.py, the one source every adapter's permissions read too
(G-01/G-03/G-04): with `home` (the workspace) given, every machinery path and all of
`var/` that lies inside a writable bind is bound read-only again, then the writable binds nested in
those (a run's OUT, a phase's own harness home) are reopened, and `.git/config` + `.git/hooks` of
every writable git root are read-only. The masked credential set is machinery.credentials(): the
usual credential dirs, every agent CLI's home (~/.dsh, ~/.codex, ~/.claude, ~/.gemini, ...) and
the homes named by DSH_HOME, CODEX_HOME, ... Other files under $HOME stay readable.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager

from konstant import machinery


@functools.lru_cache(maxsize=None)
def available() -> bool:
    exe = shutil.which("bwrap")
    if not exe or os.environ.get("KONSTANT_NO_JAIL") == "1":
        return False
    try:
        r = subprocess.run([exe, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                            "--unshare-pid", "--unshare-net", "--die-with-parent", "true"],
                           capture_output=True, timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def hidden(home=None, env=None) -> list:
    """What a jail masks: the workspace's var/secrets/ and machinery.credentials()."""
    out = [os.path.join(str(home), "var", "secrets")] if home else []
    return out + [os.path.expanduser(c) for c in machinery.credentials(env=env)]


def _inside(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip("/") + "/")


def wrap(argv, *, rw=(), hide=(), expose=(), tmpfs=(), cwd=None, net: bool = True,
         home=None) -> list:
    """The jailed argv (or argv unchanged when the jail is unavailable). `tmpfs`: directories
    replaced by an empty private tmpfs first (e.g. /tmp); `rw`: directories bound writable;
    `home`: the workspace, whose machinery stays read-only inside any writable bind (module
    docstring); `hide`: directories masked by an empty tmpfs (files: by /dev/null), never one
    that holds the workspace, a writable bind or the cwd; `expose`: files inside a hidden
    directory bound back read-only (a phase's own role token)."""
    if not available():
        return list(argv)
    a = [shutil.which("bwrap"), "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
         "--unshare-pid", "--die-with-parent"]
    if not net:
        a.append("--unshare-net")
    for p in dict.fromkeys(os.path.realpath(str(x)) for x in tmpfs if x):
        if os.path.isdir(p):
            a += ["--tmpfs", p]
    roots = [p for p in dict.fromkeys(os.path.realpath(str(x)) for x in rw if x)
             if os.path.isdir(p)]
    for p in roots:
        a += ["--bind", p, p]
    ro = []
    if home:
        guard = [os.path.realpath(str(x)) for x in machinery.jail_read_only(home)]
        repos = list(roots)
        projects = os.path.join(str(home), "projects")
        if os.path.isdir(projects):           # the workspace bound whole: every project's .git
            repos += [os.path.join(projects, d) for d in sorted(os.listdir(projects))]
        guard += [os.path.realpath(str(g)) for r in repos for g in machinery.git_guards(r)]
        ro = [p for p in dict.fromkeys(guard) if os.path.exists(p)
              and any(_inside(p, r) for r in roots)]
        for p in ro:
            a += ["--ro-bind", p, p]
        for p in roots:                       # a writable bind nested in a read-only one
            if any(_inside(p, q) and p != q for q in ro):
                a += ["--bind", p, p]
    keep = [os.path.realpath(str(x)) for x in (home, cwd) if x] + roots
    for p in dict.fromkeys(os.path.realpath(str(x)) for x in hide if x):
        if any(_inside(k, p) for k in keep):
            continue                          # never mask the workspace, a writable bind, the cwd
        if os.path.isdir(p):
            a += ["--tmpfs", p]
        elif os.path.isfile(p):
            a += ["--ro-bind", os.devnull, p]
    for p in dict.fromkeys(os.path.realpath(str(x)) for x in expose if x):
        if os.path.isfile(p):
            a += ["--ro-bind", p, p]
    if cwd:
        a += ["--chdir", os.path.realpath(str(cwd))]
    return a + ["--", *map(str, argv)]


@contextmanager
def session(argv, *, rw=(), home=None, cwd=None, net: bool = True, env=None,
            enabled: bool = True):
    """(argv, env) to run: jailed with a private TMPDIR when enabled and available."""
    env = dict(os.environ if env is None else env)
    if not (enabled and available()):
        yield list(argv), env
        return
    tmp = tempfile.mkdtemp(prefix="konstant-jail-")
    try:
        env["TMPDIR"] = tmp
        yield wrap(argv, rw=(*rw, tmp), hide=hidden(home), cwd=cwd, net=net,
                   home=home), env
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
