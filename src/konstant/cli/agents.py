"""`konstant agents sync [--check] [--harness NAME]` and `konstant agents list` (DESIGN §8, §12).

Only the surfaces of the configured harnesses are generated (docs/HARNESSES.md); `--harness NAME`
limits sync or check to one of them, and `--check` reports the drift per harness."""
from __future__ import annotations

from konstant import catalog as catalog_mod
from konstant import config as config_mod
from konstant import harnesses
from konstant.agents.generate import GenerateError, Generator
from konstant.cli.main import EXIT_FAIL, EXIT_OK


def _load(ctx):
    cfg = ctx.cfg
    root = catalog_mod.find_root(cfg.home, cfg.data["catalog"]["path"])
    return cfg, catalog_mod.load(root, check_files=True)


def _fail(msg: str) -> int:
    print(f"konstant agents: {msg}")
    return EXIT_FAIL


def cmd_sync(ctx) -> int:
    try:
        cfg, cat = _load(ctx)
        harnesses.check_types(cfg.data["harness"], cat)
        gen = Generator(cat, cfg.home, cfg.data["permissions"], harness=cfg.data["harness"],
                        gate=cfg.session_gate(), policy=cfg.data["board"]["policy"],
                        conf=cfg.confinement())
        only = ctx.args.harness
        if ctx.args.check:
            names = [only] if only else gen.harness_names()
            per = {n: gen.check(n) for n in names}
            drift = gen.check(only)
            text = [f"{n}: {'ok' if not d else f'{len(d)} out of date'}" for n, d in per.items()]
            ctx.out({"ok": not drift, "drift": drift, "harnesses": per},
                    "\n".join(drift + text + [f"konstant agents: {len(drift)} generated file(s) "
                                              "out of date - run `konstant agents sync`"]) if drift
                    else "\n".join(text + ["konstant agents: generated files match the catalog"]))
            return EXIT_FAIL if drift else EXIT_OK
        changed = gen.sync(only)
    except (catalog_mod.CatalogError, GenerateError, harnesses.HarnessError) as exc:
        return _fail(str(exc))
    ctx.out({"changed": changed, "workspace": str(cfg.home)},
            "\n".join(changed + [f"konstant agents: {len(changed)} change(s) in {cfg.home}"]))
    return EXIT_OK


def listing(cat) -> dict:
    types = {t: {"agent": cat.agent_of(t), "deliverable": cat.types[t]["deliverable"],
                 "workflow": f"workflow-{cat.workflow_of(t)}", "skills": cat.skills_of(t)}
             for t in cat.type_names()}
    producers = [v["agent"] for v in types.values()]
    root = cat.root
    agents = {a: {"file": f"agents/{a}.md", "type": cat.type_of_agent(a),
                  "skills": cat.agent_skills(a)} for a in cat.agents()}
    skills = sorted(p.name for p in (root / "skills").iterdir() if (p / "SKILL.md").is_file())
    workflows = sorted(p.stem for p in (root / "workflows").glob("*.md"))
    return {"catalog": str(root), "types": types, "agents": agents, "skills": skills,
            "workflows": workflows,
            "bijection": len(set(producers)) == len(producers) == len(types)}


def cmd_list(ctx) -> int:
    try:
        try:
            home, configured = ctx.cfg.home, ctx.cfg.data["catalog"]["path"]
        except config_mod.ConfigError:          # outside a workspace: the source-tree catalog
            home, configured = None, ""
        cat = catalog_mod.load(catalog_mod.find_root(home, configured), check_files=True)
    except catalog_mod.CatalogError as exc:
        return _fail(str(exc))
    data = listing(cat)
    lines = [f"{'type':<10} {'agent':<11} {'deliverable':<12} workflow"]
    lines += [f"{t:<10} {v['agent']:<11} {v['deliverable']:<12} {v['workflow']}"
              for t, v in data["types"].items()]
    lines += ["", f"agents ({len(data['agents'])}): " + ", ".join(data["agents"]),
              f"skills ({len(data['skills'])}): " + ", ".join(data["skills"]),
              f"workflows ({len(data['workflows'])}): " + ", ".join(data["workflows"]),
              f"one agent per type: {'yes' if data['bijection'] else 'NO'}"]
    ctx.out(data, "\n".join(lines))
    return EXIT_OK


def register(sub, leaf) -> None:
    p = sub.add_parser("agents", help="generate and list the agent catalog surfaces")
    s = p.add_subparsers(dest="agents_command", metavar="VERB")
    s.required = True
    y = s.add_parser("sync", parents=[leaf], help="render catalog/ into the surfaces of the "
                     "configured harnesses (--check: report drift, write nothing)")
    y.add_argument("--check", action="store_true", help="exit 1 naming every drifted file")
    y.add_argument("--harness", choices=list(harnesses.ADAPTERS),
                   help="only this configured harness's surfaces")
    y.set_defaults(func=cmd_sync)
    li = s.add_parser("list", parents=[leaf], help="types, agents, skills, workflows")
    li.set_defaults(func=cmd_list)
