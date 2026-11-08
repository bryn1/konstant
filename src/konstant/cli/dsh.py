"""`konstant dsh APP [ARGS...]`: start YOUR dsh session (web UI, tui or headless) in this workspace
with konstant's layers (docs/DSH.md).

It runs `dsh --profile APP --patch .dsh/konstant.patch.yml --patch .dsh/konstant-session.patch.yml
ARGS...` with DSH_HOME / DSH_AGENTS_HOME relocated into `var/harness/dsh/session/` (your own dsh
profiles, credentials, MCP servers and memory never load; the phases of `task run` keep their own
home), the model of `[harness]` for dsh in KONSTANT_MODEL, and the session's directory: the
current directory when it is inside the workspace, else the workspace (`--project SLUG`: that
project's directory; dsh's workspace-write sandbox then writes only there). The session is the
ORCHESTRATOR: the konstant-gate plugin gates its typed messages and runs the DoD loop, its
delegated children are never gated. `--dry-run` prints the argv, cwd and the environment konstant
sets instead of starting dsh. The session is NOT jailed, so before it starts dsh it refuses, exit 1
(fail closed; G-01/G-02/G-05):
  - generated dsh surfaces that differ from a fresh render (`agents sync --check` for dsh: the
    plugin and the patches the session loads are konstant's, byte for byte);
  - packages installed into the session home's profiles (they resolve before dsh's own bundles);
  - a composition (`--dump-config`, no model call) that cannot be read, or that holds any layer
    besides dsh's own bundles and konstant's two patches (an insert-only or id-patch layer in the
    session home, a launcher that forces its own DSH_HOME).
No phase can write the session home: it is under var/harness/, which every adapter and the jail
keep read-only for phases (konstant/machinery.py), and phases get a fresh dsh home each.

Host agents ([confinement] host_agents, docs/CONCEPTS.md "Confinement profiles"): unless it is
true, the session's PATH starts with `var/harness/dsh/session/bin/`, whose `dsh`, `claude`, `codex`
and `gemini` refuse (exit 126, naming the program they shadow): a model in the session that runs
`dsh ...` by name never reaches the host's own launcher, which would load the operator's personal
agent home outside this workspace's composition. konstant itself (bin/konstant, the plugin's
calls) drops that directory from its PATH (KONSTANT_SHIM_DIR), so `task run` still finds the real
harness CLIs. The session is unjailed: a program named by its absolute path is not stopped.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from konstant.cli.main import EXIT_USAGE
from konstant.harnesses import dsh as dsh_adapter
from konstant.harnesses import dsh_session
from konstant.harnesses.base import harness_home, private_dir


AGENT_CLIS = ("dsh", "claude", "codex", "gemini")


def shim_dir(ws: Path) -> Path:
    return harness_home(ws, "dsh") / "session" / "bin"


def write_shims(ws: Path, path: str) -> Path:
    """The refusing launchers for the session's PATH (host_agents = false)."""
    import shlex
    d = private_dir(shim_dir(ws))
    for name in AGENT_CLIS:
        host = shutil.which(name, path=path) or "nothing else on PATH"
        msg = (f"konstant: `{name}` is refused inside the orchestrator session ([confinement] "
               f"host_agents = false; it shadows {host}): it would start an agent outside this "
               "workspace's composition (your own launcher, its profiles and servers). Start work "
               "with bin/konstant task run, or set [confinement] host_agents = true "
               "(docs/CONCEPTS.md \"Confinement profiles\").")
        p = d / name
        p.write_text(f"#!/bin/sh\n# written by `konstant dsh` ([confinement] host_agents = false)\n"
                     f"echo {shlex.quote(msg)} >&2\nexit 126\n", encoding="utf-8")
        p.chmod(0o700)
    return d


def session_env(ws: Path, hcfg: dict, conf=None) -> dict:
    home = harness_home(ws, "dsh") / "session"
    env = {"DSH_HOME": str(home / "home"), "DSH_AGENTS_HOME": str(home / "agents"),
           "KONSTANT_HOME": str(ws)}
    models = dsh_adapter.models(hcfg)
    if models:
        env["KONSTANT_MODEL"] = models[0]
    ep = hcfg.get("endpoint") or {}
    if ep.get("base_url") and not ep.get("api_key_env"):
        env[dsh_adapter.KEY_ENV] = "unused"
    if conf is None or not conf.host_agents:
        d = str(shim_dir(ws))
        env["KONSTANT_SHIM_DIR"] = d
        env["PATH"] = d + os.pathsep + os.environ.get("PATH", os.defpath)
    return env


def _cwd(ctx, ws: Path) -> Path:
    if ctx.args.project:
        from konstant.cli.task import _project_path
        return Path(_project_path(ctx, ctx.args.project))
    here = Path.cwd().resolve()
    return here if here == ws or ws in here.parents else ws


def cmd_dsh(ctx) -> int:
    ws = Path(ctx.cfg.home).resolve()
    missing = [p for p in (dsh_adapter.PATCH, dsh_session.SESSION_PATCH, dsh_session.PLUGIN)
               if not (ws / p).is_file()]
    if missing:
        print(f"konstant dsh: {', '.join(missing)} missing: configure dsh ([harness] name = "
              "\"dsh\" or a [harness.types.<type>] row) and run `bin/konstant agents sync`",
              file=sys.stderr)
        return EXIT_USAGE
    exe = shutil.which("dsh")
    argv = [exe or "dsh", "--profile", ctx.args.app, "--patch", str(ws / dsh_adapter.PATCH),
            "--patch", str(ws / dsh_session.SESSION_PATCH), *ctx.args.args]
    extra = session_env(ws, ctx.cfg.data["harness"], ctx.cfg.confinement())
    cwd = _cwd(ctx, ws)
    if ctx.args.dry_run:
        print(json.dumps({"argv": argv, "cwd": str(cwd), "env": extra}, indent=2))
        return 0
    if not exe:
        print("konstant dsh: dsh not found on PATH (npm @deepseek-ai/dsh)", file=sys.stderr)
        return 127
    for k in ("DSH_HOME", "DSH_AGENTS_HOME"):
        private_dir(Path(extra[k]))
    if extra.get("KONSTANT_SHIM_DIR"):
        write_shims(ws, os.environ.get("PATH", os.defpath))
    env = {k: v for k, v in os.environ.items()
           if k not in ("KONSTANT_IN_TASK", "KONSTANT_RUN", "KONSTANT_ROLE")}
    env.update(extra)
    why = refusal(ctx, ws, extra)
    if why:
        print(f"konstant dsh: refused: {why}", file=sys.stderr)
        return 1
    from konstant import config
    if config.ORIG_UMASK is not None:
        os.umask(config.ORIG_UMASK)
    os.chdir(cwd)
    os.execvpe(exe, argv, env)
    return 0  # pragma: no cover


def refusal(ctx, ws: Path, extra: dict) -> str | None:
    """Why the unjailed session must not start (None: it may). Fail closed."""
    from konstant import catalog as catalog_mod
    from konstant.agents.generate import GenerateError, Generator
    cfg = ctx.cfg
    try:
        cat = catalog_mod.load(catalog_mod.find_root(cfg.home, cfg.data["catalog"]["path"]),
                               check_files=True)
        drift = Generator(cat, cfg.home, cfg.data["permissions"], harness=cfg.data["harness"],
                          gate=cfg.session_gate(), policy=cfg.data["board"]["policy"],
                          conf=cfg.confinement(),
                          memory=cfg.data["memory"]["enabled"]).check("dsh")
    except (catalog_mod.CatalogError, GenerateError) as exc:
        return f"the generated dsh surfaces cannot be checked: {exc}"
    if drift:
        return (f"generated files differ from the catalog: {', '.join(drift[:5])} - the session "
                "would load them unjailed; run `bin/konstant agents sync` (and find out what "
                "changed them)")
    residue = dsh_adapter.home_residue(Path(extra["DSH_HOME"]))
    if residue:
        return (f"packages are installed in the session's dsh home: {', '.join(residue)} - they "
                "load before dsh's own bundles; remove them")
    error, foreign = dsh_adapter.compose_layers(
        ws, ctx.args.app, [ws / dsh_adapter.PATCH, ws / dsh_session.SESSION_PATCH], extra)
    if error:
        return error
    if foreign:
        return (f"the session would load layers from outside konstant: {', '.join(foreign)} - "
                f"{dsh_adapter.FOREIGN_FIX}")
    return None


def register(sub, leaf) -> None:
    import argparse
    p = sub.add_parser("dsh", parents=[leaf], help="start your dsh session (web, tui, headless) "
                       "with the konstant gate plugin")
    p.add_argument("--project", help="run the session in this project's directory")
    p.add_argument("--dry-run", action="store_true",
                   help="print the argv, cwd and environment instead of starting dsh")
    p.add_argument("app", help="the dsh profile/app: web, tui or headless")
    p.add_argument("args", nargs=argparse.REMAINDER, help="arguments for dsh after the patches")
    p.set_defaults(func=cmd_dsh)
