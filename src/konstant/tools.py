"""The programs konstant ITSELF runs (git, bwrap, ls, ps, sh, its own Python) come from a trusted
set only, never from a PATH entry a phase could write (REVIEW L5-R1 H-01).

konstant's own processes - the task runner, the verifier, the holdout runner, intake, doctor,
the board - run unjailed as the operator's user. A program they find through the inherited PATH
can be one a phase planted: under the open profile a phase writes anywhere the user can, so
`~/.local/bin/git` (first on Ubuntu's default PATH) would run with the verifier's token and the
sealed store in reach. So:

  - TRUSTED_DIRS are the system directories; one counts only when it exists, is owned by root and
    is not writable by group or others (a writable /usr/local/bin, as some systems ship it, is
    dropped);
  - konstant's own interpreter directory (the venv's bin/) comes first: it is part of the
    integrity core (machinery.DIRS `.venv`; `own_dirs()` binds it read-only in every jail when
    the venv lies outside the workspace, e.g. a development checkout);
  - `which(name)` resolves on that path only; `env()` is an environment whose PATH is it, for the
    git and helper commands konstant starts (git itself runs helpers through PATH).

A harness CLI (claude, codex, gemini, dsh) is a PHASE program, not konstant's: it is found on the
user's PATH and started inside konstant's jail whenever a phase could have planted it (factory
mode, the open profile); doctor and the dsh preflight start it jailed as well (jailed_argv).
"""
from __future__ import annotations

import os
import shutil
import stat
import sys

TRUSTED_DIRS = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")


def _root_owned(d: str) -> bool:
    try:
        st = os.stat(d)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022


def own_bin() -> str:
    """The directory of the interpreter konstant runs on (its venv's bin/)."""
    return os.path.dirname(os.path.abspath(sys.executable))


def own_dirs() -> list:
    """What konstant executes and imports from: its interpreter's prefix (the venv) and the
    directory its package is imported from. No phase may write them (integrity core)."""
    import konstant
    out = [os.path.realpath(sys.prefix), os.path.realpath(own_bin()),
           os.path.realpath(os.path.dirname(os.path.dirname(konstant.__file__)))]
    return [p for p in dict.fromkeys(out) if p and p != "/" and os.path.isdir(p)]


def system_dirs() -> list:
    return [d for d in TRUSTED_DIRS if _root_owned(d)]


def trusted_path() -> str:
    """konstant's own PATH: its venv bin first, then the root-owned system directories."""
    return os.pathsep.join(dict.fromkeys([own_bin(), *system_dirs()]))


def which(name: str) -> str | None:
    """The absolute path of `name` on the trusted path only (None: not installed there)."""
    if os.sep in name:
        return name if os.path.isfile(name) and os.access(name, os.X_OK) else None
    return shutil.which(name, path=trusted_path())


def need(name: str) -> str:
    exe = which(name)
    if exe is None:
        raise FileNotFoundError(f"{name}: not found in konstant's trusted program directories "
                                f"({trusted_path()})")
    return exe


def git() -> str:
    """The git konstant runs (`git` as a last resort only, so a missing git fails as before)."""
    return which("git") or "/usr/bin/git"


def env(base: dict | None = None, **extra) -> dict:
    """`base` (default os.environ) with PATH set to the trusted path."""
    out = dict(os.environ if base is None else base)
    out["PATH"] = trusted_path()
    out.update(extra)
    return out


def user_writable_path_dirs(path: str | None = None) -> list:
    """The entries of PATH (default: the inherited one) this user can write: where a phase with
    host writes could plant a program (doctor shows them; konstant never resolves its own tools
    there)."""
    out = []
    for d in (path if path is not None else os.environ.get("PATH", "")).split(os.pathsep):
        if d and os.path.isdir(d) and os.access(d, os.W_OK):
            out.append(d)
    return list(dict.fromkeys(out))


def jailed_argv(argv: list, home) -> list:
    """`argv` inside konstant's jail with the integrity core of workspace `home` masked (no
    token but viewer's, no sealed store, machinery read-only): how konstant runs a harness CLI
    outside a phase (doctor's version probe, dsh's composition check). Unchanged when the jail
    is unavailable (the caller states that limit)."""
    from konstant import jail
    if not home:
        return list(argv)
    return jail.wrap(argv, hide=jail.hidden(home), home=home)
