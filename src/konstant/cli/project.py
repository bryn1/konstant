"""`konstant project add|list`."""
from __future__ import annotations

import subprocess

from konstant.cli.main import EXIT_FAIL, EXIT_OK


def cmd_add(ctx) -> int:
    a = ctx.args
    res = ctx.client().post("/api/projects", {"slug": a.slug, "name": a.name or "",
                                               "path": a.path or ""})
    path = ctx.cfg.resolve(res["path"])
    path.mkdir(parents=True, exist_ok=True)
    if a.init_git and not (path / ".git").exists():
        from konstant import tools
        r = subprocess.run([tools.git(), "init", "-q", str(path)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"konstant: git init failed in {path}: {r.stderr.strip()}")
            return EXIT_FAIL
    ctx.out(res, f"PROJECT={res['slug']} root job={res['root_job_id']} path={path}")
    return EXIT_OK


def cmd_list(ctx) -> int:
    rows = ctx.client().get("/api/projects")["projects"]
    ctx.out(rows, "\n".join(f"{r['slug']:<20} root={r['root_job_id']:<5} {r['status']:<8} "
                            f"{r['path']}" for r in rows) or "no projects")
    return EXIT_OK


def register(sub, leaf) -> None:
    p = sub.add_parser("project", help="projects (each owns a root job)")
    ps = p.add_subparsers(dest="project_cmd", metavar="ACTION")
    ps.required = True
    a = ps.add_parser("add", parents=[leaf], help="create a project and its root job")
    a.add_argument("slug")
    a.add_argument("--name")
    a.add_argument("--path", help="project directory (default projects/<slug>)")
    a.add_argument("--init-git", action="store_true", help="git init the project directory")
    a.set_defaults(func=cmd_add)
    ps.add_parser("list", parents=[leaf], help="list projects").set_defaults(func=cmd_list)
