"""The harness adapter interface (docs/HARNESSES.md, DESIGN §9).
reason: ONE interface every adapter implements (start, reach, confinement, usage); split, the
contract would live in two places.

konstant is the layer ABOVE the harness: it never runs a model loop itself, and the model belongs
to the harness. An adapter says, for one agent CLI:
  - how a headless phase is started (`argv`, `env`, `prepare`; prompt as an argv item or on stdin),
  - which surfaces that CLI reads (`files`: the generated instruction/skill/settings files),
  - how the workspace-scoped reach (design decision: edits and commands only inside the workspace,
    deny the rest) maps onto the CLI's own permission system, and what it cannot enforce (`reach`),
  - the key that selects a model, and how `doctor` detects the CLI (`binary`, `version_args`).
Every adapter keeps konstant's own guarantees, which do not depend on the harness: a phase acts as
`worker` (KONSTANT_ROLE, the CLI refuses other tokens), the runner reaps what a phase leaves running
(gate/reaper.py), and `task check` / `verify` run agent-written code in konstant.jail.

Factory mode (docs/LEVEL5.md 2.1): a phase of a job with sealed holdouts runs inside konstant.jail
WHATEVER the harness (`confine`): the root read-only, writable only the project (in factory mode
the job's clone), OUT, the phase's private TMPDIR and the harness's own per-phase home; every
machinery path read-only even inside those; var/secrets/ masked except the token of the phase's
own identity and the read-only viewer token; the sealed holdout store, the credential and agent
homes masked. The harness's own sandbox runs nested inside it. A harness that needs its own
credential file to reach its model gets exactly that file, bound read-only into its relocated
per-phase home (`jail_ro_binds`). dsh confines every phase, factory mode or not.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from konstant import machinery

# workspace paths no phase may write, whatever the harness: konstant/machinery.py is the one source
# (the Claude settings, the codex profile, the gemini policy and konstant.jail all read it)
PROTECTED_DIR_LIST = machinery.DIRS
PROTECTED_FILE_LIST = machinery.FILES
# role tokens a phase must never read (it acts as worker; viewer is read-only)
PRIVILEGED_TOKENS = machinery.PRIVILEGED_TOKENS
LEVELS = ("enforced", "partial", "none")
PLACEHOLDERS = ("prompt_file", "prompt", "agent", "cwd", "run_dir", "workspace", "model")
ARGV_PROMPT_MAX = 100 * 1024
_PH = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")


class HarnessError(Exception):
    pass


def build_argv(template: str, values: dict, stdin: bool) -> list:
    """An argv template split with shlex; placeholders substituted in ONE pass per token, so text
    substituted in (the prompt) is never scanned again (DESIGN §9)."""
    try:
        tokens = shlex.split(template)
    except ValueError as exc:
        raise HarnessError(f"[harness] command does not split: {exc}") from exc
    if not tokens:
        raise HarnessError("[harness] command is empty")
    joined = " ".join(tokens)
    if not stdin and "{prompt}" not in joined and "{prompt_file}" not in joined:
        raise HarnessError("[harness] command needs {prompt} or {prompt_file} (or stdin = true)")
    if "{prompt}" in joined and len(values["prompt"].encode()) > ARGV_PROMPT_MAX:
        raise HarnessError(f"the prompt is over {ARGV_PROMPT_MAX // 1024} KiB, too long for one "
                           "argv item: use {prompt_file} or [harness] stdin = true")
    return [_PH.sub(lambda m: str(values.get(m.group(1), "")), tok) for tok in tokens]


@dataclass
class Reach:
    """What the harness ITSELF enforces for a headless phase (konstant's own checks come on top).
    Each aspect: (level, plain-words detail)."""
    edits: tuple
    commands: tuple
    reads: tuple
    user_level: tuple

    def rows(self) -> list:
        return [("edits", *self.edits), ("commands", *self.commands), ("reads", *self.reads),
                ("user-level", *self.user_level)]

    @property
    def weakest(self) -> str:
        levels = [lvl for _a, lvl, _d in self.rows()]
        return "none" if "none" in levels else "partial" if "partial" in levels else "enforced"


@dataclass
class Phase:
    """Everything an adapter needs to start one phase."""
    values: dict          # placeholders: prompt, prompt_file, agent, cwd, run_dir, workspace
    model: str = ""
    endpoint: dict = field(default_factory=dict)
    allow: list = field(default_factory=list)      # [permissions] allow (Claude rule syntax)
    jail: bool = True                               # [gate] jail: konstant may confine the phase
    scratch: dict = field(default_factory=dict)     # per-phase state of the adapter (dsh's home)
    factory: bool = False       # a phase of a job with sealed holdouts: always jailed (LEVEL5 2.1)
    identity: str = "worker"    # whose token the phase reads (LEVEL5 2.2)
    # the scenario writer (LEVEL5 3.4): its harness home lives under `home_base` (inside the sealed
    # store) instead of var/harness/<name>/phases; `tokens` overrides the token files it may read
    # (None: its identity's and viewer's); `hide` masks more paths (job clones, run records)
    home_base: Path | None = None
    tokens: tuple | None = None
    hide: tuple = ()
    # the workspace's [confinement] (konstant/confinement.py; None = closed): `wconf` is what the
    # generated surfaces were rendered from, `conf` what THIS phase gets (wconf.for_phase: the
    # scenario writer always closed, a factory phase never with the docker socket)
    wconf: object = None
    # [memory] enabled for this phase: codex renders the server on its command line, claude
    # swaps an empty --mcp-config in when off (konstant/memory/wiring.py); the scenario writer's
    # server runs on its exported read-only view (memory/view.py)
    memory: bool = True

    @property
    def conf(self):
        from konstant import confinement
        return (self.wconf or confinement.CLOSED).for_phase(self.identity, self.factory)

    @property
    def workspace(self) -> Path:
        return Path(self.values["workspace"])

    @property
    def cwd(self) -> Path:
        return Path(self.values["cwd"])

    @property
    def run_dir(self) -> Path:
        return Path(self.values["run_dir"])

    @property
    def out(self):
        """The run's OUT dir when the runner named it (None for a one-off run)."""
        return Path(self.values["out"]) if self.values.get("out") else None


class Adapter:
    name = ""
    binary = ""
    version_args = ("--version",)
    stdin = False                      # True: the prompt goes on stdin
    instructions = "AGENTS.md"         # the instruction file it reads
    model_key = ""                     # how a model is selected (docs)
    local_models = ""                  # how it reaches a local OpenAI-compatible endpoint (docs)
    surfaces_doc = ""                  # what it reads (docs)
    uses_endpoint = False
    # whether a phase's session transcripts and state can live in a fresh per-phase home that is
    # deleted afterwards (docs/LEVEL5.md 3.4: only such a harness may run the scenario writer,
    # else a later producer on the same harness could read its transcript)
    relocatable_home = False
    home_doc = "the tool's own user-level home (konstant cannot relocate it)"

    def argv(self, ph: Phase) -> list:
        raise NotImplementedError

    def env(self, ph: Phase) -> dict:
        return {}

    # model-key env vars this harness needs: they pass the allowlisted phase env (REVIEW H-05)
    env_keys: tuple = ()

    def prepare(self, ph: Phase) -> None:
        """Create what the phase needs before start (relocated homes, the phase TMPDIR)."""

    def cleanup(self, ph: Phase) -> None:
        """Remove what prepare() created for this phase only (runs after the phase, always)."""

    def preflight(self, workspace: Path, conf=None) -> str | None:
        """Why no phase may start on this harness (None: fine). Checked once per run, before
        the first phase (dsh: its composed layers, fail closed)."""
        return None

    def measures(self, hcfg: dict) -> bool:
        """Its phase logs report tokens and cost (LEVEL5 6.2; else such a budget is refused)."""
        return False

    def usage(self, log: Path) -> dict | None:
        """{"tokens", "cost_usd"} the harness reported in the log; None: nothing (no guess)."""
        return None

    def confine(self, argv: list, ph: Phase) -> list:
        """The argv konstant actually starts: in factory mode, in the open confinement profile
        (or always, for an adapter whose harness cannot confine reads: dsh) the phase inside
        konstant.jail; else unchanged."""
        if not self.jails(ph):
            return argv
        return jailed(argv, ph, rw=self.jail_rw(ph), ro_binds=self.jail_ro_binds(ph))

    def confines(self, jail: bool = True, factory: bool = False, conf=None) -> bool:
        """Whether confine() puts the phase inside konstant.jail ([gate] jail = `jail`): every
        adapter does in factory mode (a job with sealed holdouts, docs/LEVEL5.md 2.1) and, with
        the open profile, at level 4 too: there the jail is a thin layer that keeps only the
        integrity core (konstant/confinement.py)."""
        from konstant import jail as jail_mod
        level4 = conf is not None and conf.jails_level4()
        return bool(jail) and (bool(factory) or level4) and jail_mod.available()

    def jails(self, ph: Phase) -> bool:
        return self.confines(ph.jail, ph.factory, ph.conf)

    def jail_rw(self, ph: Phase) -> list:
        """Directories the harness itself must write inside the jail (its per-phase home)."""
        return []

    def jail_ro_binds(self, ph: Phase) -> list:
        """(source, destination) files bound read-only: the harness's own credential file inside
        its relocated home (the jail masks the original with the rest of its home)."""
        return []

    def jail_env(self, ph: Phase) -> dict:
        """Environment of a jailed phase: a private TMPDIR - the jail's own empty /tmp when it
        has one (a short path: unix sockets, such as Claude Code's sandbox bridges, need one
        under ~100 bytes), else the run's tmp/ (a workspace under /tmp keeps the host /tmp,
        read-only)."""
        return {"TMPDIR": "/tmp" if phase_private_tmp(ph) else str(ph.run_dir / "tmp")}

    def files(self, gen, hcfg: dict) -> dict:
        """{workspace-relative path: content} this harness reads beyond AGENTS.md and the shared
        `.agents/skills/` (rendered by agents/generate.py)."""
        return {}

    def reach(self, hcfg: dict, perm: dict, jail: bool = True) -> Reach:
        """`jail`: [gate] jail of the workspace (only adapters that confine() read it)."""
        raise NotImplementedError

    def doctor(self, hcfg: dict, workspace: Path) -> list:
        """Extra (status, check, detail) rows for `konstant doctor`."""
        return []

    def example(self, workspace: str = "<workspace>") -> str:
        """The default command, rendered for docs and `doctor`."""
        import shlex
        ph = Phase({"prompt": "<prompt>", "prompt_file": "<run>/prompts/<label>.md",
                    "agent": "coder",
                    "cwd": f"{workspace}/projects/demo", "run_dir": f"{workspace}/var/runs/<run>",
                    "workspace": workspace})
        return shlex.join(self.argv(ph))


def private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def harness_home(workspace: Path, name: str) -> Path:
    """A per-harness home inside the workspace (var/ is 0700): user-level settings, memory,
    skills and MCP servers of the operator do not load into a phase."""
    return Path(workspace) / "var" / "harness" / name


def phase_home(ph: Phase, name: str) -> Path:
    """A FRESH home for this phase only (var/harness/<name>/phases/<label>-XXXX, 0700), removed
    by drop_home() when the phase ends: nothing a phase writes there (session transcripts, state)
    reaches a later phase (docs/LEVEL5.md 3.4)."""
    key = f"{name}_home"
    if key not in ph.scratch:
        base = private_dir(Path(ph.home_base) / name if ph.home_base
                           else harness_home(ph.workspace, name) / "phases")
        label = Path(str(ph.values.get("prompt_file") or "phase")).stem or "phase"
        ph.scratch[key] = Path(tempfile.mkdtemp(prefix=f"{label[:40]}-", dir=base))
    return ph.scratch[key]


def drop_home(ph: Phase, name: str) -> None:
    home = ph.scratch.pop(f"{name}_home", None)
    if home is not None:
        shutil.rmtree(home, ignore_errors=True)


def private_tmp(workspace) -> bool:
    """Whether a phase jail gets its own empty tmpfs on /tmp: always, unless the workspace
    itself lies under /tmp (masking /tmp would hide it)."""
    return Path(os.path.realpath(workspace)).parts[1:2] != ("tmp",)


def phase_tokens(ph: Phase) -> tuple:
    """The token files the phase's jail exposes (machinery.tokens_readable unless overridden)."""
    return machinery.tokens_readable(ph.identity) if ph.tokens is None else tuple(ph.tokens)


def phase_hidden(ph: Phase) -> list:
    """The jail's masks for this phase: the integrity core (var/secrets/, the sealed store), its
    extra `hide` paths, and what its confinement keeps out (the credential locations it does not
    pass through, the ssh-agent and docker sockets it does not get)."""
    from konstant import jail
    conf = ph.conf
    return jail.hide_core(ph.workspace) + [str(p) for p in ph.hide] + \
        conf.masked_credentials() + conf.sockets_masked()


def prompt_binds(ph: Phase) -> list:
    """The prompt file bound read-only when it lies in a masked dir (the scenario writer's run
    dir is inside the sealed store, LEVEL5 3.4)."""
    pf = ph.values.get("prompt_file")
    if not pf or not Path(str(pf)).is_file():
        return []
    real = os.path.realpath(str(pf))
    masked = [os.path.realpath(h) for h in phase_hidden(ph)]
    return [(real, real)] if any(real.startswith(m.rstrip("/") + "/") for m in masked) else []


def phase_private_tmp(ph: Phase) -> bool:
    """The phase jail gets its own empty /tmp (base.private_tmp), unless the confinement lets
    the phase write the host (host_write: it shares the host /tmp, as your own shell does)."""
    return private_tmp(ph.workspace) and not ph.conf.host_write


def home_masks(keep: list, home: str | None = None) -> list:
    """home_read = false: every entry of $HOME masked except the ones that lead to a path in
    `keep` (the workspace, the phase's writable dirs), which are walked down the same way."""
    home = os.path.realpath(home or os.path.expanduser("~"))
    keep = [os.path.realpath(str(k)) for k in keep if k]

    def under(d: str, ks: list) -> list:
        out = []
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return out
        for n in names:
            p = os.path.join(d, n)
            ks2 = [k for k in ks if k == p or k.startswith(p + "/")]
            if not ks2:
                out.append(p)
            elif p not in ks2 and os.path.isdir(p) and not os.path.islink(p):
                out += under(p, ks2)
        return out
    if any(home == k or home.startswith(k.rstrip("/") + "/") for k in keep):
        return []                                    # $HOME lies inside a kept path
    return under(home, [k for k in keep if k.startswith(home + "/")])


def factory_ro(ph: Phase) -> list:
    """Factory mode: the workspace's projects/ (the target and every other job clone) bound
    read-only even under the open profile; the phase's own clone is re-opened (LEVEL5 2.4)."""
    return [ph.workspace / "projects"] if ph.factory else []


def exe_roots(argv0: str, depth: int = 0) -> list:
    """What a jail with $HOME masked (home_read = false: the web researcher always) must keep for
    the phase's own program to start when it is installed under $HOME: the directory of the name
    on PATH, the directory of the file it resolves to, the root of an npm-style install it lies in
    (the parent of its outermost `node_modules`) or a `versions/` store, and the same for the
    interpreter of a `#!` script (`#!/usr/bin/env node` -> node)."""
    import shutil
    exe = shutil.which(str(argv0)) if argv0 else None
    if not exe:
        return []
    real = os.path.realpath(exe)
    out = [os.path.dirname(os.path.abspath(exe)), os.path.dirname(real)]
    parts = Path(real).parts
    for i, part in enumerate(parts):
        if part in ("node_modules", "versions", "lib", "libexec") and i > 1:
            out.append(str(Path(*parts[:i])))
            break
    if depth == 0:
        try:
            with open(real, "rb") as fh:
                first = fh.readline(200)
        except OSError:
            first = b""
        if first.startswith(b"#!"):
            words = first[2:].decode(errors="replace").split()
            if words and os.path.basename(words[0]) == "env" and len(words) > 1:
                words = [w for w in words[1:] if not w.startswith("-")]
            if words:
                out += exe_roots(words[0], 1)
    return list(dict.fromkeys(out))


def jail_layout(ph: Phase, rw=(), ro_binds=(), tmpdir: bool = True, keep=()) -> dict:
    """jail.wrap's arguments for this phase under its confinement (konstant/confinement.py).
    Always (the integrity core): var/secrets/ masked except the phase identity's token and
    viewer's, the sealed store masked, every machinery path read-only (jail.wrap home=), in
    factory mode projects/ read-only but the phase's clone. Then the profile: closed = the root
    read-only, writable only the project (the clone), OUT, the phase TMPDIR and `rw`, the
    credential homes, the ssh-agent and docker sockets masked, a private /tmp; open = the root
    WRITABLE (host_write), the credentials passed, the sockets reachable, the host /tmp; each
    option changes its own part (home_read, home_write, extra_read, extra_write, credentials,
    ssh_agent, docker_socket)."""
    conf, ws = ph.conf, ph.workspace
    secrets = ws / "var" / "secrets"
    tmp = [private_dir(ph.run_dir / "tmp")] if tmpdir else []
    roots = [ph.cwd] + ([ph.out] if ph.out else []) + tmp + list(rw)
    if conf.home_write and not conf.host_write:
        roots.append(Path(os.path.expanduser("~")))
    roots += [Path(os.path.expanduser(p)) for p in conf.extra_write]
    hide = phase_hidden(ph)
    if not conf.home_read:
        hide += home_masks([ws, ph.cwd, *roots, *keep])
    ro_dirs = factory_ro(ph)
    if conf.host_write:                           # root writable: konstant's own code/interpreter
        from konstant import tools                # stays read-only (REVIEW L5-R1 H-01)
        ro_dirs = ro_dirs + [Path(d) for d in tools.own_dirs()]
    return dict(rw=roots, hide=hide, home=ws, expose=[secrets / t for t in phase_tokens(ph)],
                tmpfs=("/tmp",) if phase_private_tmp(ph) else (), cwd=ph.cwd, net=True,
                ro_binds=[*ro_binds, *prompt_binds(ph)], root_rw=conf.host_write,
                ro_dirs=ro_dirs,
                late_ro=[os.path.expanduser(p) for p in conf.extra_read] + conf.cred_paths())


def jailed(argv: list, ph: Phase, rw=(), ro_binds=()) -> list:
    """The phase inside konstant.jail (jail_layout's shape for its confinement); with $HOME
    masked the phase's own program stays reachable (exe_roots)."""
    from konstant import jail
    keep = exe_roots(argv[0]) if argv and not ph.conf.home_read else []
    return jail.wrap(argv, **jail_layout(ph, rw, ro_binds, keep=keep))
