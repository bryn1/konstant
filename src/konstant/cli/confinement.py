"""`konstant confinement show`: the effective [confinement] (konstant/confinement.py) and how each
configured harness enforces each capability, at level 4 and in factory mode; `doctor` reports the
same summary (rows()).

Per harness and option the matrix names the mechanism and a level: `enforced` (konstant's jail or
the harness's own permission system holds it), `partial` (holds for some tools only), `no` (that
harness cannot hold it; the reason is in the text). konstant's own checks (the tests rule, the
verifier's re-run, holdout runs, probes) are not in the matrix: they always run closed.
"""
from __future__ import annotations

import os

from konstant import confinement as conf_mod
from konstant.cli.main import EXIT_OK

ORDER = ("claude", "codex", "gemini", "dsh", "command")


def _paths(v) -> str:
    v = ["every location and variable konstant lists (*)" if x == "*" else x for x in v]
    return ", ".join(v) if v else "none"


# options a harness never sees: the `konstant dsh` session's PATH (host_agents) and what the
# board serves from the memory vault (memory_share)
BOARD_HELD = ("host_agents", "memory_share")


def jail_how(opt: str, c, name: str = "") -> tuple:
    """How konstant's jail holds option `opt` for a jailed phase (base.jail_layout)."""
    net_off = {"codex": ("enforced", "the jail shares the host network; codex's own profile "
                         "(nested) sets network.enabled = false"),
               "claude": ("partial", "the jail shares the host network; Claude Code's sandbox "
                          "rules apply only while it nests in the jail (`doctor`: claude "
                          "sandbox)")}
    rows = {
        "network": net_off.get(name, ("no", "the jail shares the host network (the harness "
                                      "reaches its model through it): network = false is NOT "
                                      "enforced here")) if c.network is False else
        ("enforced", "the jail shares the host network (the harness reaches its model through "
         "it)"),
        "home_read": ("enforced", "your home readable, the credential locations masked unless "
                      "passed" if c.home_read else "every entry of $HOME masked except the "
                      "workspace and the phase's writable paths"),
        "home_write": ("enforced", "$HOME bound writable" if c.home_write else
                       "$HOME read-only"),
        "host_write": ("enforced", "the host root bound writable" if c.host_write else
                       "the root read-only; writable: the project (job clone), OUT, the phase "
                       "TMPDIR and home"),
        "extra_read": ("enforced", f"bound back read-only after the masks: "
                       f"{_paths(c.extra_read)}"),
        "extra_write": ("enforced", f"bound writable: {_paths(c.extra_write)}"),
        "credentials": ("enforced", "passed: " + _paths(list(c.credentials)) + "; konstant's "
                        "other credential locations masked, its credential variables dropped"),
        "ssh_agent": ("enforced", "SSH_AUTH_SOCK kept, its socket reachable" if c.ssh_agent else
                      "SSH_AUTH_SOCK dropped, its socket masked"),
        "docker_socket": ("enforced", "the docker sockets reachable, DOCKER_HOST kept"
                          if c.docker_socket else "the docker sockets masked, DOCKER_HOST "
                          "dropped"),
    }
    return rows[opt]


def own_how(name: str, opt: str, c) -> tuple:
    """How harness `name` holds `opt` itself when konstant's jail does not wrap the phase."""
    if name == "claude":
        rows = {
            "network": ("enforced", {None: "Claude Code's sandbox network rules (no domain "
                                     "allowed: its sandboxed Bash has no network)",
                                     True: "sandbox.network.allowedDomains [\"*\"]",
                                     False: "sandbox.network.allowedDomains []"}[c.network]),
            "home_read": ("partial", "sandboxed Bash reads $HOME minus the credential "
                          "locations; the Read tool stays in the working dirs" if c.home_read
                          else "sandbox denyRead ~/ (allowRead the workspace)"),
            "home_write": ("enforced", "sandbox allowWrite ~/, Edit(~/**)" if c.home_write
                           else "writes only in the workspace"),
            "host_write": ("enforced", "sandbox allowWrite /, Edit(//**)" if c.host_write
                           else "writes only in the workspace"),
            "extra_read": ("enforced", f"Read rules + additionalDirectories: "
                           f"{_paths(c.extra_read)}"),
            "extra_write": ("enforced", f"Edit rules + sandbox allowWrite: "
                            f"{_paths(c.extra_write)}"),
            "credentials": ("enforced", "left out of the sandbox denyRead: "
                            + _paths(list(c.credentials))),
            "ssh_agent": ("partial", "sandbox.network.allowAllUnixSockets (a static file "
                          "cannot name the per-login agent socket)" if c.ssh_agent else
                          "unix sockets blocked by Claude Code's sandbox"),
            "docker_socket": ("enforced", "sandbox.network.allowUnixSockets: the docker sockets"
                              if c.docker_socket else "unix sockets blocked by Claude Code's "
                              "sandbox"),
        }
    elif name == "codex":
        rows = {
            "network": ("enforced", "permissions.konstant.network.enabled = "
                        + ("false" if c.network is False else "true")),
            "home_read": ("enforced", "readable" if c.home_read else "deny rules on $HOME's "
                          "other entries"),
            "home_write": ("enforced", "$HOME = write" if c.home_write else "read"),
            "host_write": ("enforced", ":root = write" if c.host_write else ":root = read"),
            "extra_read": ("enforced", f"read rules: {_paths(c.extra_read)}"),
            "extra_write": ("enforced", f"write rules: {_paths(c.extra_write)}"),
            "credentials": ("enforced", "not denied: " + _paths(list(c.credentials))),
            "ssh_agent": ("partial", "the variable follows the option; codex's profile cannot "
                          "name a socket"),
            "docker_socket": ("partial", "the variable follows the option; codex's profile "
                              "cannot name a socket"),
        }
    elif name == "gemini":
        rows = {o: ("no", "Gemini CLI's shell commands run unconfined (only its file tools "
                    "follow the workspace directories" + (" and --include-directories"
                                                          if o in ("extra_read", "extra_write")
                                                          else "") + ")")
                for o in conf_mod.OPTIONS}
    elif name == "dsh":
        rows = {o: ("no", "konstant's jail is off: dsh's own sandbox ("
                    + ("danger-full-access" if c.writes_outside else "workspace-write")
                    + ") confines writes only, never reads") for o in conf_mod.OPTIONS}
    else:
        rows = {o: ("no", "konstant cannot see what this tool allows") for o in conf_mod.OPTIONS}
    return rows[opt]


def core_how(name: str, jailed: bool, c) -> tuple:
    if not c.integrity:
        return ("no", "OFF ([confinement] integrity = \"off\"): tokens, the holdout store and "
                "konstant's machinery are not protected; factory mode refuses to start")
    if jailed and c.docker_socket:
        return ("partial", "konstant's jail masks the tokens and the holdout store and keeps "
                "machinery read-only, but the docker socket is passed: root on this host")
    if jailed:
        return ("enforced", "konstant's jail: var/secrets/ masked but the phase's own and "
                "viewer's token, var/holdout/ masked, machinery read-only")
    return {"claude": ("partial", "Claude Code's deny rules (Read, Edit) and its sandbox for "
                       "Bash; an unsandboxed Bash would not be held"),
            "codex": ("enforced", "codex's permission profile (machinery read, tokens and "
                      "holdouts deny)"),
            "gemini": ("partial", "its policy holds the file tools; its shell is not held"),
            "dsh": ("no", "dsh without konstant's jail does not confine reads"),
            "command": ("no", "nothing konstant can enforce")}[name]


def matrix(cfg) -> dict:
    """{profile, integrity, options, harnesses: {name: {level4: {...}, factory: {...}}}}."""
    from konstant import harnesses
    from konstant import jail as jail_mod
    c = cfg.confinement()
    on = bool(cfg.data["gate"]["jail"]) and jail_mod.available()
    names = [n for n in ORDER if n in harnesses.configured(cfg.data["harness"])]
    out = {"profile": c.profile, "integrity": "on" if c.integrity else "off",
           "jail": "available" if on else ("off" if not cfg.data["gate"]["jail"]
                                           else "unavailable"),
           "options": {k: {**v, "allows": conf_mod.OPTIONS[k]["allows"],
                           "risks": conf_mod.OPTIONS[k]["risks"]}
                       for k, v in conf_mod.as_dict(c).items() if k in conf_mod.OPTIONS},
           "harnesses": {}}
    for name in names:
        ad = harnesses.ADAPTERS[name]() if name != "command" else harnesses.Choice(
            "command", "", "x {prompt}", False, "").adapter
        per = {}
        for mode, factory in (("level4", False), ("factory", True)):
            cc = c.for_phase("worker", factory)
            jailed = ad.confines(on, factory, cc)
            rows = {o: dict(zip(("enforced", "how"), jail_how(o, cc, name) if jailed
                                else own_how(name, o, cc)))
                    for o in conf_mod.OPTIONS if o not in BOARD_HELD}
            rows["integrity core"] = dict(zip(("enforced", "how"), core_how(name, jailed, cc)))
            per[mode] = {"jailed": jailed, "options": rows}
        out["harnesses"][name] = per
    out["memory"] = ("shared with your own tools: notes konstant did not write are recalled too"
                     if c.memory_share else "konstant's own notes only: a note added or changed "
                     "in memory/ outside konstant is not served to a phase") + \
        " (the board holds it for every harness; phases never read memory/ directly)"
    out["host_agents"] = ("the `konstant dsh` session may run the host's agent launchers by name"
                          if c.host_agents else "the `konstant dsh` session's PATH starts with "
                          "refusing dsh/claude/codex/gemini shims")
    return out


def text(m: dict) -> str:
    lines = [f"confinement: profile {m['profile']}, integrity {m['integrity']}, konstant's jail "
             f"{m['jail']}", "", f"{'option':<14} {'value':<22} source"]
    for k, v in m["options"].items():
        val = v["value"] if not isinstance(v["value"], list) else (", ".join(v["value"]) or "[]")
        val = {None: "harness default", True: "true", False: "false"}.get(val, val) \
            if not isinstance(val, str) else val
        lines.append(f"{k:<14} {str(val):<22} "
                     f"{v['source']}")
    lines += ["", f"memory: {m['memory']}", f"host agents: {m['host_agents']}"]
    for name, per in m["harnesses"].items():
        for mode, label in (("level4", "level 4"), ("factory", "factory mode")):
            p = per[mode]
            lines += ["", f"{name} ({label}): " + ("in konstant's jail" if p["jailed"]
                                                   else "not jailed: the harness's own rules")]
            for o, r in p["options"].items():
                lines.append(f"  {o:<15} {r['enforced']:<9} {r['how']}")
    return "\n".join(lines)


def rows(cfg) -> list:
    """`doctor` rows: the profile, the integrity core, open-profile hazards."""
    c = cfg.confinement()
    out = []
    if not c.integrity:
        out.append(("FAIL", "integrity core", "OFF ([confinement] integrity = \"off\"): phases "
                    "can read every token and the holdout store and write konstant's machinery, "
                    "so `verified` means nothing; factory mode refuses to start; set integrity = "
                    "\"on\" (docs/CONCEPTS.md \"Confinement profiles\")"))
    else:
        out.append(("PASS", "integrity core", "on: holdout store unreadable, only the phase's own "
                    "token readable, machinery not writable (in every profile)"))
    widened = [k for k in conf_mod.OPTIONS
               if getattr(c, k) not in (None, ()) and getattr(c, k) != getattr(conf_mod.CLOSED, k)]
    status = "WARN" if c.open or widened else "PASS"
    out.append((status, "confinement", f"profile {c.profile}" + (
        f"; wider than closed: {', '.join(widened)}" if widened else "") +
        "; `bin/konstant confinement show` prints what each harness enforces"))
    if c.docker_socket:
        out.append(("WARN", "docker socket", "passed to level-4 phases: it is root on this host, "
                    "so the integrity core does not hold against a phase that uses it (factory "
                    "mode never passes it)"))
    if c.ssh_agent or c.cred_paths():
        hit = self_login()
        if hit:
            out.append(("WARN", "ssh to this host", f"{hit} is in your own authorized_keys: a "
                        "phase with your ssh credentials can log in to THIS host and leave "
                        "konstant's jail (the integrity core then does not hold)"))
    if c.host_agents:
        out.append(("WARN", "host agents", "the `konstant dsh` session may run the host's own "
                    "agent launchers (your personal agent setup) by name"))
    return out


def self_login(home: str | None = None) -> str | None:
    """A public key in ~/.ssh/*.pub that ~/.ssh/authorized_keys accepts (public files only)."""
    d = os.path.join(home or os.path.expanduser("~"), ".ssh")
    try:
        auth = open(os.path.join(d, "authorized_keys"), encoding="utf-8").read()
        pubs = [f for f in sorted(os.listdir(d)) if f.endswith(".pub")]
    except OSError:
        return None
    for f in pubs:
        try:
            parts = open(os.path.join(d, f), encoding="utf-8").read().split()
        except OSError:
            continue
        if len(parts) >= 2 and parts[1] in auth:
            return f"~/.ssh/{f}"
    return None


def cmd_show(ctx) -> int:
    m = matrix(ctx.cfg)
    ctx.out(m, text(m))
    return EXIT_OK


def register(sub, leaf) -> None:
    p = sub.add_parser("confinement", parents=[leaf], help="the confinement profile: what "
                       "phases may see and do, per harness")
    s = p.add_subparsers(dest="sub", metavar="SUBCOMMAND")
    s.required = True
    sh = s.add_parser("show", parents=[leaf], help="print the effective profile, options and "
                      "how each configured harness enforces them")
    sh.set_defaults(func=cmd_show)
