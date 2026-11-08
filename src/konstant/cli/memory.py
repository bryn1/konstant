"""`konstant memory recall|store|note|list|show|log|reindex` and `konstant mcp memory`
(wave L5-M; docs/CONCEPTS.md "Memory").

The CLI is the documented fallback of the MCP tools: the same board routes, the same identity
rules (a phase acts as its own identity, else `--as` / `[client] default_role`). Reads may use any
token; `reindex` is the owner's or the orchestrator's.
"""
from __future__ import annotations

import os
import sys

from konstant.cli.main import EXIT_FAIL, EXIT_OK


def _text(arg: str) -> str:
    return sys.stdin.read() if arg == "-" else arg


def _run() -> str:
    run = os.environ.get("KONSTANT_RUN", "").rstrip("/")
    return os.path.basename(run) if run else ""


def cmd_recall(ctx) -> int:
    from konstant.memory.mcp import render_hits
    a = ctx.args
    res = ctx.client().get("/api/memory/recall", q=" ".join(a.query), limit=a.limit or None,
                           pool=a.pool or None)
    ctx.out(res, render_hits(res))
    return EXIT_OK


def _write(ctx, route: str, title: str, text: str) -> int:
    a = ctx.args
    res = ctx.client().post(route, {"text": text, "title": title, "tags": a.tag or [],
                                    "links": a.link or [], "run": _run()})
    ctx.out(res, f"STORED {res['path']} commit={res['commit'][:12]} pool={res['pool']}"
            + (f" (embedding: {res['embed_error']})" if res.get("embed_error") else ""))
    return EXIT_OK


def cmd_store(ctx) -> int:
    return _write(ctx, "/api/memory/store", ctx.args.title or "", _text(ctx.args.text))


def cmd_note(ctx) -> int:
    return _write(ctx, "/api/memory/note", ctx.args.title, _text(ctx.args.text))


def cmd_list(ctx) -> int:
    a = ctx.args
    res = ctx.client().get("/api/memory/notes", limit=a.limit, pool=a.pool or None)
    lines = [f"{n['updated'][:19]:<20} {n['pool']:<7} {n['trust']:<28} {n['path']}"
             for n in res["notes"]]
    if res.get("hidden"):
        lines.append(f"({res['hidden']} note(s) in pools this identity does not read)")
    ctx.out(res, "\n".join(lines) or "no notes")
    return EXIT_OK


def cmd_show(ctx) -> int:
    res = ctx.client().get("/api/memory/note", path=ctx.args.path)
    head = f"# {res['title']}  ({res['pool']}, tags: {', '.join(res['tags']) or '-'})"
    ctx.out(res, head + "\n\n" + res["body"].rstrip())
    return EXIT_OK


def cmd_log(ctx) -> int:
    rows = ctx.client().get("/api/memory/writes", limit=ctx.args.limit)["writes"]
    ctx.out({"writes": rows}, "\n".join(
        f"{r['at']} {r['state']:<8} {r['actor']:<13} {r['kind']:<5} "
        f"{r['path'] or '(' + str(r['reason']) + ')'}" + (f" job={r['job_id']}" if r['job_id']
                                                          else "")
        for r in rows) or "no memory writes")
    return EXIT_OK


def cmd_reindex(ctx) -> int:
    res = ctx.client().post("/api/memory/reindex", {})
    ctx.out(res, f"REINDEXED notes={res['notes']} indexed={res['indexed']} "
            f"embedded={res['embedded']}" + (f" (embedding: {res['embed_error']})"
                                             if res.get("embed_error") else ""))
    return EXIT_OK


def cmd_mcp_memory(ctx) -> int:
    """The stdio MCP server. Nothing but MCP messages on stdout: errors go to stderr."""
    from konstant.client import ClientError, identity, in_task
    from konstant.memory import view
    from konstant.memory.mcp import Server
    if os.environ.get(view.VIEW_ENV) and os.environ.get(view.OUT_ENV):
        # the scenario writer: its read-only copy of the readable notes, notes collected after
        # the phase into the sealed pool (memory/view.py); it holds no token
        return Server(view.ViewClient(os.environ[view.VIEW_ENV],
                                      os.environ[view.OUT_ENV])).serve()
    if in_task() and identity() == "scenario":
        print("konstant mcp memory: the scenario writer has no memory view for this phase "
              "(docs/CONCEPTS.md \"Memory\")", file=sys.stderr)
        return EXIT_FAIL
    try:
        client = ctx.client()
    except ClientError as exc:
        print(f"konstant mcp memory: {exc.message}", file=sys.stderr)
        return EXIT_FAIL
    return Server(client).serve()


def register(sub, leaf) -> None:
    p = sub.add_parser("memory", help="the memory vault: recall, store, notes (docs/CONCEPTS.md "
                                      "\"Memory\")")
    ms = p.add_subparsers(dest="memory_cmd", metavar="ACTION")
    ms.required = True
    r = ms.add_parser("recall", parents=[leaf], help="search memory (lexical, or hybrid with "
                                                     "[memory] embed_endpoint)")
    r.add_argument("query", nargs="+")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--pool", help="one pool only: shared, sealed (judges, owner), notes")
    r.set_defaults(func=cmd_recall)
    s = ms.add_parser("store", parents=[leaf],
                      help="store a fact (the shared pool; the judges' sealed one)")
    s.add_argument("text", help="the fact, or - for stdin")
    s.add_argument("--title")
    for q in (s,):
        q.add_argument("--tag", action="append", help="a tag (repeatable)")
        q.add_argument("--link", action="append", help="a [[wikilink]] target (repeatable)")
    s.set_defaults(func=cmd_store)
    n = ms.add_parser("note", parents=[leaf], help="write or replace a named note")
    n.add_argument("title")
    n.add_argument("text", help="the note's Markdown body, or - for stdin")
    n.add_argument("--tag", action="append", help="a tag (repeatable)")
    n.add_argument("--link", action="append", help="a [[wikilink]] target (repeatable)")
    n.set_defaults(func=cmd_note)
    li = ms.add_parser("list", parents=[leaf], help="recent notes you may read")
    li.add_argument("--limit", type=int, default=20)
    li.add_argument("--pool")
    li.set_defaults(func=cmd_list)
    sh = ms.add_parser("show", parents=[leaf], help="print one note")
    sh.add_argument("path", help="vault-relative path, e.g. worker/facts/....md")
    sh.set_defaults(func=cmd_show)
    lg = ms.add_parser("log", parents=[leaf], help="who wrote what (stored and refused writes)")
    lg.add_argument("--limit", type=int, default=50)
    lg.set_defaults(func=cmd_log)
    ms.add_parser("reindex", parents=[leaf], help="rebuild the recall index from the vault "
                  "(owner, orchestrator)").set_defaults(func=cmd_reindex)
    m = sub.add_parser("mcp", help="MCP servers konstant ships (stdio)")
    mm = m.add_subparsers(dest="mcp_cmd", metavar="SERVER")
    mm.required = True
    mm.add_parser("memory", parents=[leaf], help="the memory MCP server: kb_recall, kb_store, "
                  "kb_note").set_defaults(func=cmd_mcp_memory)
