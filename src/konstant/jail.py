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


@functools.lru_cache(maxsize=None)
def nests() -> bool:
    """Whether a bubblewrap sandbox starts INSIDE konstant's jail (its own pid namespace and
    /proc, as Claude Code's and dsh's Linux sandboxes start one): the outer jail's shape with a
    private /tmp, and a second bwrap that unshares pid and network inside it."""
    if not available():
        return False
    exe = shutil.which("bwrap")
    inner = [exe, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-pid",
             "--unshare-net", "--die-with-parent", "true"]
    try:
        r = subprocess.run(wrap(inner, tmpfs=("/tmp",)), capture_output=True, timeout=15,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def hidden(home=None, env=None) -> list:
    """What a jail masks: the workspace's var/secrets/, the sealed holdout store
    (machinery.SEALED) and machinery.credentials()."""
    return hide_core(home) + [os.path.expanduser(c) for c in machinery.credentials(env=env)]


def _inside(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip("/") + "/")


def wrap(argv, *, rw=(), hide=(), expose=(), tmpfs=(), cwd=None, net: bool = True,
         home=None, binds=(), ro_binds=(), root_rw: bool = False, ro_dirs=(),
         late_ro=()) -> list:
    """The jailed argv (or argv unchanged when the jail is unavailable). `tmpfs`: directories
    replaced by an empty private tmpfs first (e.g. /tmp); `rw`: directories (or files) bound
    writable; `home`: the workspace, whose machinery stays read-only inside any writable bind
    (module docstring); `hide`: paths masked by an empty tmpfs (a directory) or /dev/null
    (anything else: a file, a socket), never one that holds the workspace, a writable bind or the
    cwd; `expose`: files inside a hidden directory bound back read-only (a phase's own role token);
    `binds`: (source, destination) pairs bound writable at ANOTHER path (a holdout's materialised
    tree at the project's own path, so the code under test sees the path the tests rule shows
    it); `ro_binds`: (source file, destination) pairs bound READ-ONLY at another path, last (a
    harness's own credential file inside the phase's relocated home: docs/LEVEL5.md 2.1).
    The open confinement profile (konstant/confinement.py) uses three more: `root_rw` binds the
    host root WRITABLE instead of read-only (the machinery of `home` and `ro_dirs` are then bound
    read-only wherever they are); `ro_dirs`: directories bound read-only like machinery (a factory
    phase's target and the other job clones); `late_ro`: paths bound back read-only after the
    masks (a credential the profile passes through, an extra_read path under a mask)."""
    if not available():
        return list(argv)
    a = [shutil.which("bwrap"), "--bind" if root_rw else "--ro-bind", "/", "/", "--dev", "/dev",
         "--proc", "/proc", "--unshare-pid", "--die-with-parent"]
    if not net:
        a.append("--unshare-net")
    for p in dict.fromkeys(os.path.realpath(str(x)) for x in tmpfs if x):
        if os.path.isdir(p):
            a += ["--tmpfs", p]
    roots = [p for p in dict.fromkeys(os.path.realpath(str(x)) for x in rw if x)
             if os.path.exists(p)]
    masked = [os.path.realpath(str(x)) for x in hide if x]
    # a writable dir INSIDE a masked one (the scenario writer's drafts and home in the sealed
    # store, docs/LEVEL5.md 3.4) is bound AFTER the mask: the rest of that dir stays masked
    late = [p for p in roots if any(_inside(p, m) and p != m for m in masked)]
    roots = [p for p in roots if p not in late]
    for p in roots:
        a += ["--bind", p, p]
    for src, dst in binds:
        a += ["--bind", os.path.realpath(str(src)), os.path.realpath(str(dst))]
    ro = []
    scope = roots + (["/"] if root_rw else [])
    if home or ro_dirs:
        guard = [os.path.realpath(str(x)) for x in machinery.jail_read_only(home)] if home else []
        guard += [os.path.realpath(str(x)) for x in ro_dirs if x]
        repos = list(roots)
        projects = os.path.join(str(home), "projects") if home else ""
        if projects and os.path.isdir(projects):    # the workspace bound whole: every .git
            repos += [os.path.join(projects, d) for d in sorted(os.listdir(projects))]
        guard += [os.path.realpath(str(g)) for r in repos for g in machinery.git_guards(r)]
        ro = [p for p in dict.fromkeys(guard) if os.path.exists(p)
              and any(_inside(p, r) for r in scope)]
        for p in ro:
            a += ["--ro-bind", p, p]
        rebound = [p for p in roots if any(_inside(p, q) and p != q for q in ro)]
        for p in rebound:                     # a writable bind nested in a read-only one
            a += ["--bind", p, p]
        for p in ro:                          # ... keeps the guards that lie inside it
            if any(_inside(p, r) and p != r for r in rebound):
                a += ["--ro-bind", p, p]
    keep = [os.path.realpath(str(x)) for x in (home, cwd) if x
            and os.path.realpath(str(x)) not in late] + roots + \
        [os.path.realpath(str(d)) for _s, d in binds]
    for p in dict.fromkeys(os.path.realpath(str(x)) for x in hide if x):
        if any(_inside(k, p) for k in keep):
            continue                          # never mask the workspace, a writable bind, the cwd
        if os.path.isdir(p):
            a += ["--tmpfs", p]
        elif os.path.exists(p):
            a += ["--ro-bind", os.devnull, p]
    for p in late:
        a += ["--bind", p, p]
        for q in ro:                          # machinery inside a late writable bind stays ro
            if _inside(q, p) and q != p:
                a += ["--ro-bind", q, q]
    for p in dict.fromkeys(os.path.realpath(str(x)) for x in late_ro if x):
        if os.path.exists(p) and any(_inside(p, m) for m in masked) and \
                not any(_inside(p, os.path.realpath(str(h))) for h in hide_core(home)):
            a += ["--ro-bind", p, p]
    for p in dict.fromkeys(os.path.realpath(str(x)) for x in expose if x):
        if os.path.isfile(p):
            a += ["--ro-bind", p, p]
    for src, dst in ro_binds:
        if os.path.isfile(str(src)):
            a += ["--ro-bind", os.path.realpath(str(src)), os.path.realpath(str(dst))]
    if cwd:
        a += ["--chdir", os.path.realpath(str(cwd))]
    return a + ["--", *map(str, argv)]


def hide_core(home) -> list:
    """The masks no option lifts (the integrity core's read side): var/secrets/ and the sealed
    holdout store of workspace `home`."""
    if not home:
        return []
    return [os.path.join(str(home), "var", "secrets"), *map(str, machinery.sealed(home))]


@contextmanager
def session(argv, *, rw=(), home=None, cwd=None, net: bool = True, env=None,
            enabled: bool = True, binds=()):
    """(argv, env) to run: jailed with a private TMPDIR when enabled and available."""
    env = dict(os.environ if env is None else env)
    if not (enabled and available()):
        yield list(argv), env
        return
    tmp = tempfile.mkdtemp(prefix="konstant-jail-")
    try:
        env["TMPDIR"] = tmp
        yield wrap(argv, rw=(*rw, tmp), hide=hidden(home), cwd=cwd, net=net,
                   home=home, binds=binds), env
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
