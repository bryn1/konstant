"""Confinement profiles (docs/CONCEPTS.md "Confinement profiles", DESIGN §9.1, docs/LEVEL5.md 2.1):
what a phase may see and do, chosen in konstant.toml as ONE profile plus per-capability options
that override it, around an integrity core that no profile opens.

  [confinement]
  profile = "closed"        # closed (default) | open
  integrity = "on"          # on | off (off: level 4 only, with profile = "open"; doctor FAIL;
                            # factory mode refuses to start)
  # any option below overrides the profile's value (OPTIONS: what each allows and risks)

closed  the 0.1.0 reach: a phase writes only inside its project (and OUT), the credential and agent
        homes konstant lists are masked, no ssh agent, no docker socket.
open    the phase gets the host like the owner's own shell: read and write anywhere the user can,
        network, ssh and the ssh agent, the docker socket, the user's credential files and env.

The INTEGRITY CORE holds in every profile (always in factory mode; at level 4 unless the owner
turned it off): the sealed holdout store is unreadable (machinery.SEALED); every token but the
phase's own identity's (and the read-only viewer's) is unreadable; konstant's machinery
(machinery.DIRS/FILES: the catalog, the generated harness surfaces, var/ bookkeeping, the board
DB that holds the verdict history, .git of the workspace) is not writable; in factory mode also
the target repository and the other job clones. It protects the meaning of "verified", not the
host. Every adapter and konstant.jail read the profile from here; konstant's own checks (the tests
rule, the verifier's re-run, holdout runs, probes) never read it: they always run closed.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, fields, replace
from pathlib import Path

from konstant import machinery

PROFILES = ("closed", "open")
ALL = "*"                       # credentials = ["*"]: every credential location and variable
_ENV = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")

# the options table: ONE source for the config check, `konstant confinement show`, doctor and the
# docs (docs/CONCEPTS.md copies it; tests/unit/test_confinement.py checks they agree).
# kind: flag (true/false), tri (true/false; unset = each harness's own default), paths, creds
OPTIONS = {
    "network": dict(
        kind="tri", closed=None, open=True,
        allows="commands of a phase reach the network (beyond the harness's own model traffic)",
        risks="exfiltration of anything the phase can read; downloads that run code"),
    "home_read": dict(
        kind="flag", closed=True, open=True,
        allows="read your home folder outside the workspace (the credential locations stay "
               "masked unless `credentials` passes them)",
        risks="private files (notes, other projects, browser data) reach the model"),
    "home_write": dict(
        kind="flag", closed=False, open=True,
        allows="write anywhere in your home folder",
        risks="a phase can plant code your own unjailed sessions run later (shell rc files, "
              "agent homes, ~/.local/bin)"),
    "host_write": dict(
        kind="flag", closed=False, open=True,
        allows="write anywhere you can outside the workspace (implies home_write)",
        risks="anything your user can change on this host, including other repositories"),
    "extra_read": dict(
        kind="paths", closed=(), open=(),
        allows="read these paths even where the profile masks them",
        risks="what is in them reaches the model"),
    "extra_write": dict(
        kind="paths", closed=(), open=(),
        allows="write these paths",
        risks="whatever later reads those paths trusts what a phase wrote"),
    "credentials": dict(
        kind="creds", closed=(), open=(ALL,),
        allows="pass these credential files/folders (e.g. ~/.ssh, a token file) and $VARIABLES "
               "through; \"*\" = every location and variable konstant lists",
        risks="the phase can act as you on every service those credentials reach"),
    "ssh_agent": dict(
        kind="flag", closed=False, open=True,
        allows="use your ssh agent (SSH_AUTH_SOCK and its socket)",
        risks="ssh to every server your agent's keys open, without seeing a key; an ssh login "
              "into THIS host leaves konstant's jail"),
    "docker_socket": dict(
        kind="flag", closed=False, open=True,
        allows="use the docker daemon (its socket, DOCKER_HOST); never in factory mode",
        risks="the docker socket is root on this host: a phase that uses it can read and change "
              "anything, the integrity core included (so factory mode never passes it)"),
    "memory_share": dict(
        kind="flag", closed=False, open=True,
        allows="the memory vault is shared with your own tools: notes you add or edit in "
               "memory/ yourself (an editor, Obsidian) are recalled by phases as well as the "
               "notes konstant wrote",
        risks="anything that can write memory/ outside konstant steers every later phase, "
              "unattributed; private notes you keep there reach the model"),
    "host_agents": dict(
        kind="flag", closed=False, open=False,
        allows="the orchestrator session started by `konstant dsh` may run the host's own agent "
               "launchers (dsh, claude, codex, gemini) by name",
        risks="a launcher that loads your personal agent setup (its profiles, servers, "
              "passwords) runs outside the workspace's composition and every gate"),
}
FLAGS = tuple(k for k, v in OPTIONS.items() if v["kind"] in ("flag", "tri"))
LISTS = tuple(k for k, v in OPTIONS.items() if v["kind"] in ("paths", "creds"))
KEYS = ("profile", "integrity") + tuple(OPTIONS)


class ConfinementError(ValueError):
    """[confinement] is malformed, or an option reaches into the integrity core."""


@dataclass(frozen=True)
class Confinement:
    profile: str = "closed"
    integrity: bool = True
    network: bool | None = None
    home_read: bool = True
    home_write: bool = False
    host_write: bool = False
    extra_read: tuple = ()
    extra_write: tuple = ()
    credentials: tuple = ()
    ssh_agent: bool = False
    docker_socket: bool = False
    host_agents: bool = False
    memory_share: bool = False
    set_by: tuple = ()              # the options konstant.toml sets (the rest: the profile)

    @property
    def open(self) -> bool:
        return self.profile == "open"

    @property
    def writes_outside(self) -> bool:
        """Whether a phase may write outside its project, OUT and its own home."""
        return self.host_write or self.home_write or bool(self.extra_write)

    def jails_level4(self) -> bool:
        """Open profile: every phase runs in konstant's thin jail at level 4 too, because the jail
        is what keeps the integrity core around a phase that otherwise has the host."""
        return self.open and self.integrity

    def for_phase(self, identity: str = "worker", factory: bool = False) -> "Confinement":
        """The confinement one phase gets. The scenario writer handles sealed content: it always
        runs closed (an open one could copy its drafts where producers read). Factory mode never
        passes the docker socket (root on the host: it would void the integrity core) and never
        runs with the integrity core off."""
        if identity == "scenario":
            return CLOSED
        if factory:
            return replace(self, docker_socket=False, integrity=True)
        return self

    def cred_paths(self, env=None) -> list:
        """The credential locations passed through, expanded (`*`: every one konstant lists)."""
        out = []
        for c in self.credentials:
            if c == ALL:
                out += machinery.credentials(env=env)
            elif not c.startswith("$"):
                out.append(c)
        return list(dict.fromkeys(os.path.realpath(os.path.expanduser(p)) for p in out))

    def cred_env(self) -> set:
        names = set()
        for c in self.credentials:
            if c == ALL:
                names |= set(machinery.CREDENTIAL_ENV)
            elif c.startswith("$"):
                names.add(c[1:])
        return names

    def masked_credentials(self, harness: str | None = None, env=None) -> list:
        """machinery.credentials() minus what `credentials` passes through (expanded)."""
        keep = set(self.cred_paths(env))
        out = [os.path.expanduser(c) for c in machinery.credentials(harness, env=env)]
        return [c for c in out if os.path.realpath(c) not in keep]

    def env_drop(self) -> list:
        """Environment variables a phase does not get: the credential variables konstant lists
        (machinery.CREDENTIAL_ENV) that `credentials` does not pass, SSH_AUTH_SOCK without
        ssh_agent, DOCKER_HOST without docker_socket."""
        keep = self.cred_env()
        out = [v for v in machinery.CREDENTIAL_ENV if v not in keep]
        if not self.ssh_agent:
            out.append("SSH_AUTH_SOCK")
        if not self.docker_socket:
            out.append("DOCKER_HOST")
        return list(dict.fromkeys(out))

    def sockets_masked(self, env=None) -> list:
        """The ssh-agent and docker sockets a phase's jail masks (by this profile)."""
        env = os.environ if env is None else env
        out = []
        if not self.ssh_agent and env.get("SSH_AUTH_SOCK"):
            out.append(env["SSH_AUTH_SOCK"])
        if not self.docker_socket:
            out += list(machinery.DOCKER_SOCKETS)
            if env.get("XDG_RUNTIME_DIR"):
                out.append(os.path.join(env["XDG_RUNTIME_DIR"], "docker.sock"))
            host = env.get("DOCKER_HOST", "")
            if host.startswith("unix://"):
                out.append(host[len("unix://"):])
        return [p for p in dict.fromkeys(out) if p]

    def value(self, name: str):
        return getattr(self, name)

    def source(self, name: str) -> str:
        return "option" if name in self.set_by else f"profile {self.profile}"


CLOSED = Confinement()


def _profile_defaults(profile: str) -> dict:
    return {k: (tuple(v[profile]) if isinstance(v[profile], tuple) else v[profile])
            for k, v in OPTIONS.items()}


def _inside(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip("/") + "/")


def _check_path(name: str, p: str, home: Path | None, write: bool) -> None:
    if not isinstance(p, str) or not p.strip():
        raise ConfinementError(f"{name}: {p!r} is not a path")
    if not (p.startswith("/") or p.startswith("~")) or ".." in p.split("/"):
        raise ConfinementError(f"{name}: {p!r} must be an absolute path or start with ~ "
                               "(no '..')")
    if home is None:
        return
    real = os.path.realpath(os.path.expanduser(p))
    ws = os.path.realpath(str(home))
    core = [os.path.join(ws, "var", "secrets")] + [str(Path(ws) / d) for d in machinery.SEALED]
    if write:
        core += [str(Path(ws) / d) for d in (*machinery.DIRS, *machinery.FILES)]
        core += [os.path.join(ws, "var")]
    for c in core:
        if _inside(real, c):
            raise ConfinementError(f"{name}: {p!r} lies inside the integrity core ({c}): no "
                                   "option opens it (docs/CONCEPTS.md \"Confinement profiles\")")


def parse(raw: dict | None, home: Path | None = None) -> Confinement:
    """The [confinement] table -> a Confinement (fail closed: an unknown key, a wrong type, an
    option reaching into the integrity core or integrity = "off" without profile = "open")."""
    raw = dict(raw or {})
    unknown = sorted(set(raw) - set(KEYS))
    if unknown:
        raise ConfinementError(f"unknown key '{unknown[0]}' (allowed: {', '.join(KEYS)})")
    profile = raw.get("profile", "closed")
    if profile not in PROFILES:
        raise ConfinementError(f"profile = {profile!r}: one of {', '.join(PROFILES)}")
    integrity = raw.get("integrity", "on")
    if integrity not in ("on", "off"):
        raise ConfinementError(f"integrity = {integrity!r}: \"on\" or \"off\"")
    if integrity == "off" and profile != "open":
        raise ConfinementError("integrity = \"off\" needs profile = \"open\" (a closed profile "
                               "keeps the integrity core)")
    vals = _profile_defaults(profile)
    for k in FLAGS:
        if k in raw:
            if not isinstance(raw[k], bool):
                raise ConfinementError(f"{k} must be true or false, got {raw[k]!r}")
            vals[k] = raw[k]
    for k in LISTS:
        if k not in raw:
            continue
        v = raw[k]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ConfinementError(f"{k} must be a list of strings")
        for x in v:
            if k == "credentials" and (x == ALL or x.startswith("$")):
                if x != ALL and not _ENV.fullmatch(x):
                    raise ConfinementError(f"credentials: {x!r} is not a $VARIABLE name")
                continue
            _check_path(k, x, home, write=(k == "extra_write"))
        vals[k] = tuple(v)
    if vals["host_write"]:
        vals["home_write"] = True
    return Confinement(profile=profile, integrity=(integrity == "on"),
                       set_by=tuple(k for k in OPTIONS if k in raw), **vals)


def of(cfg) -> Confinement:
    """The workspace's confinement (config.Config or its data dict)."""
    data = getattr(cfg, "data", cfg)
    home = getattr(cfg, "home", None)
    return parse(data.get("confinement"), home)


def as_dict(conf: Confinement) -> dict:
    out = {"profile": conf.profile, "integrity": "on" if conf.integrity else "off"}
    for f in fields(conf):
        if f.name in OPTIONS:
            v = getattr(conf, f.name)
            out[f.name] = {"value": list(v) if isinstance(v, tuple) else v,
                           "source": conf.source(f.name)}
    return out
