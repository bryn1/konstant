"""DeepSeek Harness (`dsh`, MIT, npm `@deepseek-ai/dsh`). Checked against the installed
`dsh --help` / `dsh headless --help` (0.2.1-alpha.3) and its docs (cli-help, sandbox, approval,
agent-instructions, skill-filesystem, providers; docs/HARNESSES.md cites them).

Start: `dsh --profile headless --patch <workspace>/.dsh/konstant.patch.yml -` (the task on stdin).
The generated patch sets the sandbox to `workspace-write` (Linux: bubblewrap/Landlock; the write
root is the session cwd = the project dir, plus a private, ephemeral /tmp), the approval policy to
`never` (an escalation request is rejected, never asked), the instruction root marker to
`konstant.toml` (the workspace AGENTS.md loads from a project sub-directory) and the skill roots to
the workspace's `.agents/skills` only. DSH_HOME and DSH_AGENTS_HOME point at a FRESH directory per
phase (`var/harness/dsh/phases/<label>-XXXX/`, removed when the phase ends; G-01: a shared
home let one phase plant a profile layer that loaded into every later phase), so neither the
operator's own dsh profiles, credentials, MCP servers, AGENTS.md and skills nor anything an earlier
phase wrote loads into a phase. With `[harness.endpoint]` the patch adds an OpenAI-compatible
provider `konstant`; the model is selected per phase through KONSTANT_MODEL.
dsh's own sandbox confines writes only (its documented limit: reads are not confined), so konstant
runs every dsh PHASE inside konstant.jail (bubblewrap): the root read-only, writes only to the
project dir, OUT, the phase's own fresh dsh home and a private /tmp, every konstant machinery path
read-only even inside those (konstant/machinery.py: the generated surfaces, var/, the operator's
session home), `var/secrets/` masked except the phase identity's token (worker, or a factory
identity: docs/LEVEL5.md 2.2) and the viewer token, the credential and agent homes masked. dsh's
own sandbox runs nested inside it.
Without a working bwrap (or with [gate] jail = false) the phase runs unjailed and `doctor` says
reads are not confined. The network stays open and there is no per-command allow list.
The session surfaces (the konstant-gate plugin, its patch, the agent profiles) are in
dsh_session.py.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from konstant.harnesses import dsh_session
from konstant.harnesses.base import (Adapter, Phase, Reach, harness_home, jail_layout,
                                     private_dir)

PATCH = ".dsh/konstant.patch.yml"
PHASES = "phases"                  # var/harness/dsh/phases/: one fresh home per phase
KEY_ENV = "KONSTANT_ENDPOINT_KEY"


def _y(s: str) -> str:
    return json.dumps(s)          # a JSON string is a valid YAML scalar


def models(hcfg: dict) -> list:
    """Every model the toml names for a dsh phase (default + per-type), first mention first."""
    out = []
    if hcfg.get("name") == "dsh" and hcfg.get("model"):
        out.append(hcfg["model"])
    for row in (hcfg.get("types") or {}).values():
        if row.get("name", hcfg.get("name")) == "dsh" and row.get("model"):
            out.append(row["model"])
    return list(dict.fromkeys(out))


def sandbox_mode(conf=None) -> str:
    """dsh's own sandbox mode for the confinement (konstant/confinement.py): workspace-write
    (writes only under the session cwd) unless the profile lets a phase write outside its
    project; then danger-full-access, and konstant's jail is the write boundary (a dsh phase
    with such a profile never starts without the jail: Dsh.preflight)."""
    return "danger-full-access" if conf is not None and conf.writes_outside else "workspace-write"


def sandbox_lines(mode: str) -> list:
    return ["- id: sandbox-policy", "  config:", f"    mode: {mode}",
            "    workspaceRoot: !!js process.cwd()",
            "- id: approval", "  config:", "    policy: never",
            # the preset selector must name the (mode, never) bundle, or the
            # permission plugin refuses to start (it matched no shipped preset; seen live)
            "- id: permission", "  config:", "    presets:", "      workspace-write:",
            "        sandbox: workspace-write", "        approval: ask", "      konstant:",
            f"        sandbox: {mode}", "        approval: never",
            "    defaultPreset: konstant"]


def patch(ws, hcfg: dict, header: str, conf=None, memory: bool = True) -> str:
    lines = [f"# {header}", "# konstant's dsh layer: workspace-scoped reach for headless phases "
             "(docs/HARNESSES.md)"] + sandbox_lines(sandbox_mode(conf)) + [
             "- id: agent-instructions", "  config:", "    maxBytes: 65536",
             "    projectRootMarkers: [konstant.toml]",
             "- id: skill-filesystem", "  config:", "    includeDefaultRoots: false",
             f"    customSkillDirs: [{_y(str(ws / '.agents' / 'skills'))}]"]
    ep = hcfg.get("endpoint") or {}
    ms = models(hcfg)
    if ep.get("base_url"):
        lines += ["- id: llm-deepseek", "  disabled: true",
                  "- id: llm-pi-ai", "  config:", "    providers:", "      konstant:",
                  "        displayName: konstant endpoint",
                  f"        apiKeyEnv: {ep.get('api_key_env') or KEY_ENV}",
                  "        api: openai-completions", f"        baseURL: {_y(ep['base_url'])}",
                  "        models:"] + [f"          - id: {_y(m)}" for m in ms or ["default"]]
        default = ms[0] if ms else "default"
        lines += ["- id: agent-default-model", "  config:", "    provider: konstant",
                  f"    model: !!js process.env.KONSTANT_MODEL || {_y(default)}"]
    from konstant.memory import wiring
    lines += wiring.dsh_lines(ws, memory)       # konstant's memory MCP server (an inserted row)
    return "\n".join(lines) + "\n"


class Dsh(Adapter):
    name = "dsh"
    binary = "dsh"
    stdin = True
    model_key = ("[harness] model -> KONSTANT_MODEL, read by the generated patch "
                 "(agent-default-model); needs [harness.endpoint]")
    local_models = ("[harness.endpoint] base_url -> an llm-pi-ai provider `konstant` "
                    "(openai-completions: vLLM, llama.cpp, Ollama /v1/chat/completions)")
    surfaces_doc = ("AGENTS.md (root marker konstant.toml), .agents/skills/*/SKILL.md (the only "
                    "skill root), .dsh/konstant.patch.yml (passed with --patch)")
    uses_endpoint = True
    relocatable_home = True
    home_doc = "DSH_HOME + DSH_AGENTS_HOME: a fresh directory per phase, removed after it"

    def argv(self, ph: Phase) -> list:
        return [self.binary, "--profile", "headless", "--patch", str(ph.workspace / PATCH), "-"]

    def _root(self, ph: Phase) -> Path:
        """The phase's own fresh dsh root (home/ + agents/), created on first use."""
        if "dsh_root" not in ph.scratch:
            import tempfile
            base = private_dir(Path(ph.home_base) / "dsh" if ph.home_base
                               else harness_home(ph.workspace, "dsh") / PHASES)
            label = Path(str(ph.values.get("prompt_file") or "phase")).stem or "phase"
            root = Path(tempfile.mkdtemp(prefix=f"{label[:40]}-", dir=base))
            private_dir(root / "home")
            private_dir(root / "agents")
            ph.scratch["dsh_root"] = root
        return ph.scratch["dsh_root"]

    def env(self, ph: Phase) -> dict:
        root = self._root(ph)
        env = {"DSH_HOME": str(root / "home"), "DSH_AGENTS_HOME": str(root / "agents"),
               "DSH_PERMISSION_MODE": sandbox_mode(ph.wconf)}
        if ph.model:
            env["KONSTANT_MODEL"] = ph.model
        ep = ph.endpoint or {}
        if ep.get("base_url") and not ep.get("api_key_env"):
            env[KEY_ENV] = "unused"       # pi-ai wants a key variable; a local server ignores it
        return env

    def prepare(self, ph: Phase) -> None:
        self._root(ph)

    def cleanup(self, ph: Phase) -> None:
        import shutil
        root = ph.scratch.pop("dsh_root", None)
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)

    def preflight(self, workspace: Path, conf=None) -> str | None:
        """A phase starts only on a composition konstant can read and that holds no layer from
        outside it (G-02/G-05: fail closed). (gate/harness.py Harness.check also refuses a dsh
        phase whose confinement needs the jail when the jail cannot wrap it.)"""
        error, foreign = compose_layers(Path(workspace))
        if error == "dsh not on PATH":
            return None                   # the start itself fails with 127 and says so
        if error:
            return f"dsh: {error}"
        if foreign:
            return (f"dsh: a phase would load layers from outside konstant: {', '.join(foreign)} "
                    f"- {FOREIGN_FIX}")
        return None

    def files(self, gen, hcfg: dict) -> dict:
        conf = getattr(gen, "conf", None)
        return {PATCH: patch(gen.ws, hcfg, gen.header, conf, getattr(gen, "memory", True)),
                **dsh_session.files(gen, hcfg)}

    def confine(self, argv: list, ph: Phase) -> list:
        """The phase inside konstant.jail (dsh's sandbox does not confine reads). Writable:
        the project, OUT and this phase's own dsh root, plus what the confinement profile opens
        (base.jail_layout); konstant's machinery stays read-only inside them (jail.wrap home=)."""
        from konstant import jail
        if not self.jails(ph):
            return argv
        return jail.wrap(argv, **jail_layout(ph, rw=[self._root(ph)], tmpdir=False))

    def confines(self, jail: bool = True, factory: bool = False, conf=None) -> bool:
        """Every dsh phase, factory mode or not (dsh's sandbox does not confine reads), unless
        the owner turned the integrity core off (open profile, level 4: nothing is masked)."""
        from konstant import jail as jail_mod
        off = conf is not None and not conf.integrity and not factory
        return bool(jail) and not off and jail_mod.available()

    def jail_env(self, ph: Phase) -> dict:
        return {}                      # dsh's own sandbox gives the phase a private /tmp

    def reach(self, hcfg: dict, perm: dict, jail: bool = True) -> Reach:
        from konstant import jail as jail_mod
        jailed = jail and jail_mod.available()
        reads = (("enforced", "konstant runs every dsh phase in its bubblewrap jail: var/secrets/ "
                  "is masked except the worker and viewer tokens, the credential and agent homes "
                  "konstant lists (~/.ssh, ~/.dsh, ~/.codex, ~/.claude, ...; docs/CONCEPTS.md) "
                  "are masked; other files in your home stay readable") if jailed else
                 ("none", "reads are not confined: konstant's jail is " +
                  ("off ([gate] jail = false)" if not jail else "unavailable (no working bwrap)")
                  + ", so a phase can read var/secrets/ (every role token) and your credential "
                  "files; role separation inside a dsh phase is procedural"))
        return Reach(
            edits=("enforced", "sandbox workspace-write: file tools and commands write only under "
                   "the session cwd (the project dir) and a private /tmp; escalation rejected; "
                   "in the jail konstant's machinery stays read-only even there") if jailed else
                  ("enforced", "sandbox workspace-write: file tools and commands write only under "
                   "the session cwd (the project dir) and a private /tmp; escalation rejected"),
            commands=("partial", "no per-command allow list: any command runs inside that write "
                      "boundary; the network is open" + ("" if jailed else
                                                        "; .git/config of the project is writable")),
            reads=reads,
            user_level=("enforced", "DSH_HOME and DSH_AGENTS_HOME: a fresh directory per phase, "
                        "removed after it: no user profiles, credentials, MCP servers, AGENTS.md "
                        "or skills, nothing an earlier phase planted; a run starts only when "
                        "the composed layers are dsh's own bundles and konstant's patch"))

    def doctor(self, hcfg: dict, workspace: Path) -> list:
        rows = [layers(workspace)]
        if Path(workspace).resolve().parts[1:2] == ("tmp",):
            rows.append(("WARN", "dsh /tmp", f"{workspace} is under /tmp, which dsh's sandbox "
                         "replaces with an empty private /tmp: a phase cannot see bin/konstant or "
                         "the workspace outside its project; install konstant elsewhere"))
        if not (hcfg.get("endpoint") or {}).get("base_url"):
            rows.append(("INFO", "dsh provider", "no [harness.endpoint]: dsh uses its own default "
                         "provider with the relocated DSH_HOME (no saved credentials there): set "
                         "[harness.endpoint] base_url, or export the provider's key variable"))
        return rows


_ORIGIN = re.compile(r"^# == (.+)$", re.M)


def origins(dump: str) -> list:
    """Every layer origin `dsh --dump-config` names: the `# == <origin>` header of each block and
    every origin of its `patched by A, B` list (a bundle name, or the absolute path of a patch
    file; app-boot renderConfigDump)."""
    out = []
    for m in _ORIGIN.finditer(dump):
        base, _, by = m.group(1).partition(", patched by ")    # dsh: patchedBy.join(', ')
        out += [o.strip() for o in [base, *by.split(", ")] if o.strip()]
    return list(dict.fromkeys(out))


def _fresh(workspace: Path):
    """A throwaway (Phase, env) with its own empty dsh home, as a phase gets one."""
    ph = Phase({"workspace": workspace, "cwd": workspace, "run_dir": workspace,
                "prompt_file": "compose"})
    return ph, Dsh().env(ph)


def _dump(exe: str, workspace: Path, profile: str, patches: list, env: dict) -> tuple:
    import subprocess
    argv = [exe, "--profile", profile]
    for p in patches:
        argv += ["--patch", str(p)]
    try:
        r = subprocess.run([*argv, "--dump-config"], cwd=str(workspace),
                           env={**os.environ, **env}, capture_output=True, text=True,
                           timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"`dsh --dump-config` did not run: {exc}", ""
    if r.returncode != 0:
        return (f"`dsh --profile {profile} --dump-config` failed: "
                + (r.stderr or r.stdout).strip()[-300:]), ""
    return None, r.stdout


UNREADABLE = ("could not read the composition: `dsh --profile {p} --dump-config` exited 0 but "
              "{why} (dsh needs Node.js >= 22: check `node --version` for the node your dsh runs "
              "on; a launcher that prints its own output instead of dsh's has the same effect)")


def compose_layers(workspace: Path, profile: str = "headless", patches: list | None = None,
                   env: dict | None = None) -> tuple:
    """Compose a dsh profile (`--dump-config`, no model call) the way it will run and return
    (error, foreign). It judges the COMPOSED result and fails closed (G-02/G-05):
      - a baseline composes the profile with a fresh, empty DSH_HOME and no patch: it must name
        at least one layer, and dsh must have created that home's profile (else a launcher
        forces its own DSH_HOME);
      - the real composition (the app, konstant's patches, `env`; default: a phase's fresh home)
        must name every one of konstant's patches (else nothing was really composed);
      - foreign = every origin that is neither one of konstant's patch files nor a bundle the
        baseline composed: an id-patch AND an insert-only layer of a profile, a home layer, a
        bundle added to a profile's package.json.
    error = why the composition could not be read (None when it was): callers fail closed."""
    import shutil
    exe = shutil.which("dsh")
    if not exe:
        return "dsh not on PATH", []
    workspace = Path(workspace)
    patches = patches if patches is not None else [workspace / PATCH]
    scratch = []
    try:
        bph, benv = _fresh(workspace)
        scratch.append(bph)
        error, base_dump = _dump(exe, workspace, profile, [], benv)
        if error:
            return error, []
        base = origins(base_dump)
        if not base:
            return UNREADABLE.format(p=profile, why="printed no layer"), []
        foreign = []
        if not (Path(benv["DSH_HOME"]) / "profiles" / profile).is_dir():
            foreign.append("DSH_HOME ignored (the empty home konstant set stayed empty: your "
                           "dsh launcher sets its own home, whose profiles would load)")
        if env is None:
            ph, env = _fresh(workspace)
            scratch.append(ph)
        error, dump = _dump(exe, workspace, profile, patches, env)
        if error:
            return error, []
        seen = origins(dump)
        ours = {os.path.realpath(str(p)) for p in patches}
        named = {os.path.realpath(o) for o in seen if o.startswith("/")}
        missing = [str(p) for p in patches if os.path.realpath(str(p)) not in named]
        if missing:
            return UNREADABLE.format(p=profile, why="the dump names no layer from "
                                     + ", ".join(missing)), []
        foreign += [o for o in seen if (o.startswith("/") and os.path.realpath(o) not in ours)
                    or (not o.startswith("/") and o not in base)]
        return None, foreign
    finally:
        for ph in scratch:
            Dsh().cleanup(ph)


def home_residue(home: Path) -> list:
    """Packages installed into a dsh home's profiles: a profile's node_modules resolve before the
    installation's own bundles, so the dump would show a shipped name for foreign code."""
    out = []
    profiles = Path(home) / "profiles"
    if profiles.is_dir():
        for d in sorted(profiles.iterdir()):
            for name in ("node_modules", ".dsh-module-fallback"):
                if (d / name).exists():
                    out.append(str(d / name))
    return out


FOREIGN_FIX = ("remove that layer, or point PATH at a stock dsh (npm @deepseek-ai/dsh) if your "
               "dsh launcher sets its own DSH_HOME")


def layers(workspace: Path) -> tuple:
    """The doctor row, fail closed: a phase must compose dsh's own bundles and konstant's patch
    only; an unreadable composition or any other layer is a FAIL (no phase would start)."""
    error, foreign = compose_layers(workspace)
    if error == "dsh not on PATH":
        return ("INFO", "dsh layers", "dsh not on PATH; profile layers not checked")
    if error:
        return ("FAIL", "dsh layers", f"{error}; no dsh phase starts until it composes")
    if foreign:
        return ("FAIL", "dsh layers", f"a phase would load layers from outside konstant: "
                f"{', '.join(foreign)} - {FOREIGN_FIX}; no dsh phase starts until then")
    return ("PASS", "dsh layers", "a phase composes only dsh's shipped bundles and "
            ".dsh/konstant.patch.yml, in a fresh DSH_HOME of its own")
