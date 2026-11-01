"""`konstant doctor` rows for factory mode (docs/LEVEL5.md 2.1, 2.2, 3.4).

  factory jail       every phase of a job with sealed holdouts runs in konstant's jail, on any
                     harness; without the jail such a job refuses to start (exit 2)
  factory harness    per configured harness: confined in factory mode, and whether its home is
                     relocated per phase (only such a harness may run the scenario writer)
  claude sandbox     (claude configured) whether Claude Code's own sandbox runs nested inside the
                     jail, or the jail is the boundary with Claude Code's sandbox off
  identities         the factory identities' tokens: present, 0600
"""
from __future__ import annotations

import os
import shutil
import stat


def rows(cfg) -> list:
    from konstant import harnesses
    from konstant import jail as jail_mod
    from konstant.board.policy import IDENTITIES
    out = []
    on = bool(cfg.data["gate"]["jail"])
    if on and jail_mod.available():
        out.append(("PASS", "factory jail", "a job with sealed holdouts runs every phase in "
                    "konstant's jail on any harness (claude, codex, gemini, dsh, command): its "
                    "own job clone writable, the target read-only, only its own identity's token "
                    "readable, the holdout store masked"))
    else:
        out.append(("WARN", "factory jail", "konstant's jail is " + (
            "off ([gate] jail = false)" if not on else "unavailable (no working bubblewrap)")
            + ": a job with sealed holdouts refuses to start (exit 2, `holdouts need a confined "
            "phase`); nothing falls back to unconfined phases"))
    names = harnesses.configured(cfg.data["harness"])
    parts, fixed = [], []
    for name in names:
        ad = harnesses.adapter(name)
        parts.append(f"{name}: {ad.home_doc}")
        if not ad.relocatable_home:
            fixed.append(name)
    if fixed:
        out.append(("INFO", "factory harness", "; ".join(parts) + f". {', '.join(fixed)} cannot "
                    "relocate its home per phase: never used for the scenario writer (its "
                    "transcript would stay readable to a later producer)"))
    else:
        out.append(("PASS", "factory harness", "; ".join(parts)))
    if "claude" in names:
        out.append(claude_row(cfg.home))
    out.append(identities_row(cfg, IDENTITIES))
    return out


def claude_row(home=None) -> tuple:
    import sys

    from konstant import jail as jail_mod
    from konstant.harnesses.base import private_tmp
    from konstant.harnesses.claude import sandbox_nests
    if sandbox_nests(home):
        return ("PASS", "claude sandbox", "factory mode: Claude Code's own Bash sandbox runs "
                "nested inside konstant's jail" + ("" if sys.platform != "darwin" else
                                                   " (macOS: Seatbelt)"))
    nested = "starts" if jail_mod.nests() else "does not start"
    socat = "present" if shutil.which("socat") else "missing"
    tmp = "" if home is None or private_tmp(home) else ("; the workspace is under /tmp, so a "
                                                        "phase has no short private /tmp")
    return ("INFO", "claude sandbox", f"factory mode: Claude Code's sandbox cannot run inside "
            f"konstant's jail here (a nested bubblewrap {nested} in the jail; socat {socat}"
            f"{tmp}): a "
            "claude phase in factory mode runs with Claude Code's sandbox off and konstant's jail "
            "as the boundary")


def identities_row(cfg, identities: dict) -> tuple:
    bad = []
    for label in identities:
        p = cfg.secrets_dir / f"{label}.token"
        if not p.exists():
            bad.append(f"{p.name} missing")
        elif stat.S_IMODE(os.stat(p).st_mode) != 0o600:
            bad.append(f"{p.name} is {oct(stat.S_IMODE(os.stat(p).st_mode))}")
    if bad:
        return ("WARN", "identities", "; ".join(bad) + ": `bin/konstant board init` mints the "
                "factory identities (planner, dod-reviewer, scenario, factory) without touching "
                "existing tokens")
    return ("PASS", "identities", f"{len(identities)} factory identity tokens (planner, "
            "dod-reviewer, scenario: worker; factory: orchestrator), 0600; the board refuses "
            "the identity pairs that must differ. One model may play every role (docs/LEVEL5.md "
            "§9 Q1): the separation is the identity, the context each phase gets and the jail's "
            "file isolation, not a second model")
