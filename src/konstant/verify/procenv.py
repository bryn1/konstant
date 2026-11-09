"""Environments for the commands the verifier starts: scrubbed, and for git additionally pinned.

A probe or re-run starts with the caller's environment minus anything that carries a konstant
setting or looks like a credential. Git is further pinned so a repo's own config cannot make a
read-only shape execute something (a gpg program, a credential helper, an fsmonitor hook, a hook,
a transport): no system or global config, protocols off. Repo-local config cannot be switched off,
so the git shapes are plumbing that never converts worktree content (no `status`, no
`ls-remote`: a clean filter or an uploadpack would run; REVIEW F-04).
"""
from __future__ import annotations

import os

SECRET_WORDS = ("TOKEN", "SECRET", "KEY", "PASSWORD")

_GIT_CONFIG = ("'gpg.program=/bin/false' 'core.fsmonitor=false' 'credential.helper=' "
               "'core.askpass=/bin/false' 'http.sslVerify=true' 'core.hooksPath=/dev/null' "
               "'protocol.allow=never' 'core.untrackedCache=false' 'safe.directory=*'")


def scrub_env(base: dict | None = None, trusted_path: bool = True) -> dict:
    """Copy of `base` (default os.environ) without KONSTANT_* and secret-looking variables. With
    `trusted_path` (the default) PATH is konstant's trusted program dirs, never the inherited one
    a phase could have planted a tool on (REVIEW L5-R1 H-01); a jailed scenario RUN keeps it
    (the program must resolve inside the jail) by passing trusted_path=False."""
    from konstant import tools
    src = os.environ if base is None else base
    out = {}
    for name, value in src.items():
        up = name.upper()
        if up.startswith("KONSTANT_") or any(w in up for w in SECRET_WORDS):
            continue
        out[name] = value
    if trusted_path:
        out["PATH"] = tools.trusted_path()
    return out


def git_env(base: dict | None = None) -> dict:
    env = scrub_env(base)
    env.update(GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM="1", GIT_PAGER="cat",
               GIT_OPTIONAL_LOCKS="0", GIT_SSH_COMMAND="/bin/false", GIT_NO_REPLACE_OBJECTS="1",
               GIT_CONFIG_PARAMETERS=_GIT_CONFIG, LC_ALL="C")
    return env
