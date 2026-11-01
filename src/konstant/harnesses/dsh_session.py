"""The dsh SESSION surfaces (docs/DSH.md): what a person's own dsh session in a konstant workspace
loads, as opposed to `.dsh/konstant.patch.yml`, the reach of a headless phase.

  .dsh/konstant-session.patch.yml  inserts the konstant-gate plugin with this workspace's config
  .dsh/konstant-gate.mjs           the plugin itself (konstant/harnesses/dsh_gate/, vendored build)
  .dsh/agents/<agent>.md           the composed agent profiles: dsh has no named subagent profiles,
                                   so the orchestrating session starts each phase as a `subagent`
                                   whose prompt is that file followed by the phase brief

`konstant dsh <app> [args]` starts dsh with both patches (cli/dsh.py). The plugin brings the
runner's loop into the session: the task gate on every typed message of the
session (never on a delegated child, never inside a runner phase), the DoD loop at the end of a
gated turn (resume up to [gate] max_resumes, stop when the first reason repeats), and at MET with
a job the close-out + `konstant verify` (`konstant task close`), whose FAIL resumes the session.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PLUGIN_SRC = Path(__file__).with_name("dsh_gate")
BUNDLE = PLUGIN_SRC / "konstant-gate.mjs"
SESSION_PATCH = ".dsh/konstant-session.patch.yml"
PLUGIN = ".dsh/konstant-gate.mjs"
AGENTS_DIR = ".dsh/agents/"


def bundle_text() -> str:
    """The vendored plugin build (the release ships it; `dsh_gate/build.mjs` rebuilds it)."""
    return BUNDLE.read_text(encoding="utf-8")


def bundle_source_sha() -> str:
    """The sha256 the bundle's header says it was built from."""
    for line in bundle_text().splitlines()[:5]:
        if "source-sha256=" in line:
            return line.split("source-sha256=", 1)[1].split()[0]
    return ""


def source_sha() -> str:
    return hashlib.sha256((PLUGIN_SRC / "index.ts").read_bytes()).hexdigest()


def plugin_config(ws: Path, gate: dict, policy: dict) -> dict:
    return {"konstant": str(ws / "bin" / "konstant"), "home": str(ws),
            "maxResumes": int(gate.get("max_resumes", 3)),
            "maxVerifyRounds": int(policy.get("max_rounds", 3)),
            "verify": bool(gate.get("verify_after_close", True)),
            "fileJob": bool(gate.get("file_job", False)),
            # [notify] kind = "chat": the orchestrator chat is the intake (docs/LEVEL5.md 4.0)
            **({"chat": True} if gate.get("chat") else {})}


def session_patch(ws: Path, gate: dict, policy: dict, header: str) -> str:
    cfg = plugin_config(ws, gate, policy)
    lines = [f"# {header}",
             "# konstant's dsh SESSION layer (docs/DSH.md): the task gate + DoD loop plugin for your",
             "# own dsh session; load it after .dsh/konstant.patch.yml (`bin/konstant dsh web`).",
             "# Values come from konstant.toml ([gate], [board.policy]); change them there and run",
             "# `bin/konstant agents sync`.",
             "- insert:", "    - id: konstant-gate",
             f"      name: {json.dumps(str(ws / PLUGIN))}", "      config:"]
    lines += [f"        {k}: {json.dumps(v)}" for k, v in cfg.items()]
    return "\n".join(lines) + "\n"


def plugin_file(header: str) -> str:
    return f"// {header}\n" + bundle_text()


def files(gen, hcfg: dict) -> dict:
    gate = getattr(gen, "gate", None) or {}
    policy = getattr(gen, "policy", None) or {}
    out = {SESSION_PATCH: session_patch(gen.ws, gate, policy, gen.header),
           PLUGIN: plugin_file(gen.header)}
    for agent in gen.cat.agents():
        out[f"{AGENTS_DIR}{agent}.md"] = gen.header + "\n" + gen.agent_prompt(agent)
    return out
