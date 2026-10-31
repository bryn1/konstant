"""`konstant job ...`: file, read and move jobs through their lifecycle.

Every rule is enforced by the board; this client only reads files and shapes requests. A refusal
comes back as the board's own message (exit 1), an unknown id as exit 2.
"""
from __future__ import annotations

import os
import re
import sys

from konstant.board import dod
from konstant.cli.main import EXIT_FAIL, EXIT_OK, warn

_KV = re.compile(r"^(VERIFY_CMD|CONTROL_CMD)\s*[:=]\s*(.*\S)\s*$")
_EXIT = re.compile(r"^(VERIFY_EXIT|CONTROL_EXIT)=(-?\d+)\s*$")
_BIND = re.compile(r"^(COMMIT|BASE)=([0-9A-Za-z._/-]+)\s*$")
OUTPUT_CAP = 4000


def read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def parse_evidence(path: str) -> dict:
    """Evidence file -> the close payload. Missing lines are left out; the board names them."""
    text = read_text(path)
    out: dict = {"probes": [], "verify_output": text.encode("utf-8")[:OUTPUT_CAP]
                 .decode("utf-8", "ignore")}
    exits = []
    for line in text.splitlines():
        s = line.strip()
        m = _KV.match(s)
        if m:
            out.setdefault(m.group(1).lower(), m.group(2))
            continue
        m = _EXIT.match(s)
        if m:
            if m.group(1) == "VERIFY_EXIT":
                exits.append(int(m.group(2)))
            else:
                out.setdefault("control_exit", int(m.group(2)))
            continue
        m = _BIND.match(s)
        if m:
            out.setdefault(m.group(1).lower(), m.group(2))
        elif s.startswith("PROBE:") or s.startswith("PROBE-REFUSED:"):
            out["probes"].append(s)
        elif s.startswith("DOCS:") and "docs" not in out:
            out["docs"] = s[len("DOCS:"):].strip()
    if exits:   # any red line wins: never close on red
        out["verify_exit"] = next((e for e in exits if e != 0), 0)
    if path != "-":
        out["evidence_path"] = os.path.realpath(path)
    return out


def _line(j: dict) -> str:
    return f"{j['display_id']:<10} {j['status']:<21} {j['type']:<9} {j['title']}"


def _show(j: dict) -> str:
    keys = ("id", "display_id", "project", "type", "status", "priority", "requested_by",
            "assignee", "after_id", "verify_round", "closed_by", "created_at", "updated_at")
    out = [f"{k:<14} {j.get(k)}" for k in keys]
    out += ["title          " + j["title"], "", "acceptance:", j.get("acceptance") or "(none)"]
    if j.get("evidence"):
        ev = j["evidence"]
        out += ["", f"evidence: verify_cmd={ev.get('verify_cmd')!r} "
                    f"verify_exit={ev.get('verify_exit')} self_attested={ev.get('self_attested')}"]
        out += [f"  {p}" for p in ev.get("probes", [])]
    for t in j.get("trail", []):
        out.append(f"{t['ts']} {t['kind']:<8} {t['actor']}: {t['body']}")
    return "\n".join(out)


def _done(ctx, res: dict) -> int:
    for w in res.get("warnings", []):
        warn(w)
    ctx.out(res, f"JOB={res['id']} display={res['display_id']} status={res['status']}")
    return EXIT_OK


def cmd_add(ctx) -> int:
    a = ctx.args
    brief = read_text(a.brief)
    body = {"title": a.title, "project": a.project, "brief": brief,
            "type": a.type or "", "parent": a.parent or "", "priority": a.priority,
            "after": a.after or "", "approval": a.approval,
            "holdout_required": a.holdout_required}
    res = ctx.client().post("/api/jobs", body)
    for ln, why in probe_refusals(ctx, brief):        # the same lint `job lint` runs (F-30)
        warn(f"PROBE REFUSED: {ln!r} - {why}: `konstant verify` will report it unverifiable")
    return _done(ctx, res)


def cmd_list(ctx) -> int:
    a = ctx.args
    rows = ctx.client().get("/api/jobs", status=a.status, type=a.type, project=a.project,
                            self_attested=a.self_attested, roots=a.tree, limit=a.limit)["jobs"]
    if a.tree:
        text = "\n".join("  " * r["depth"] + _line(r) for r in
                         sorted(rows, key=lambda r: [int(x) for x in r["display_id"].split(".")]))
    else:
        text = "\n".join(_line(r) for r in rows)
    ctx.out(rows, text or "no jobs")
    return EXIT_OK


def cmd_show(ctx) -> int:
    res = ctx.client().get(f"/api/jobs/{ctx.args.id}", trail=ctx.args.trail)
    ctx.out(res, _show(res))
    return EXIT_OK


def cmd_search(ctx) -> int:
    a = ctx.args
    rows = ctx.client().get("/api/search", q=" ".join(a.words), open=a.open,
                            project=a.project)["jobs"]
    ctx.out(rows, "\n".join(_line(r) for r in rows) or "no match")
    return EXIT_OK


def _verb(verb: str, body_fn=None):
    def run(ctx) -> int:
        body = body_fn(ctx.args) if body_fn else {}
        return _done(ctx, ctx.client().post(f"/api/jobs/{ctx.args.id}/{verb}", body))
    return run


def cmd_note(ctx) -> int:
    res = ctx.client().post(f"/api/jobs/{ctx.args.id}/trail",
                            {"kind": ctx.args.kind, "body": " ".join(ctx.args.text)})
    ctx.out(res, f"JOB={res['job_id']} {res['kind']} appended (trail id {res['trail_id']})")
    return EXIT_OK


def cmd_review(ctx) -> int:
    a = ctx.args
    body = {"verdict": read_text(a.verdict), "done": read_text(a.done),
            "verdict_path": os.path.realpath(a.verdict), "done_path": os.path.realpath(a.done)}
    return _done(ctx, ctx.client().post(f"/api/jobs/{a.id}/review", body))


def cmd_lint(ctx) -> int:
    brief = read_text(ctx.args.file)
    rows = dod.lint(brief)
    has_dod = bool(dod.extract_acceptance(brief))
    data = {"acceptance": has_dod, "flags": [{"class": c, "row": r} for c, r in rows]}
    lines = [] if has_dod else ["REFUSED at filing: no 'DoD:' / 'Acceptance:' line - "
                                "acceptance is required"]
    lines += [f"{c}: {r!r} - {dod.ADVICE[c]}" for c, r in rows]
    refused = probe_refusals(ctx, brief)
    data["probe_refusals"] = [{"line": ln, "reason": why} for ln, why in refused]
    lines += [f"PROBE REFUSED: {ln!r} - {why}" for ln, why in refused]
    ctx.out(data, "\n".join(lines) or "ok: DoD present, no row flagged")
    return EXIT_OK if has_dod and not refused else EXIT_FAIL


def probe_refusals(ctx, brief: str) -> list:
    """PROBE lines the verifier's allowlist would refuse, caught at filing time (DESIGN §7).
    Roots: the verifier's own root builder over the board's projects (REVIEW F-13: lint and
    verify agree); with no board, [verify] path_roots + the workspace's projects/ dir."""
    from konstant.client import ClientError
    from konstant.verify import probe, shapes
    from konstant.verify.verifier import build_roots
    try:
        cfg = ctx.cfg
    except Exception:  # no workspace: shapes only, relative to the current directory
        cfg = None
    if cfg is None:
        roots = shapes.Roots.build(os.getcwd(), {})
    else:
        try:
            projects = ctx.client("viewer").get("/api/projects")["projects"]
        except ClientError:
            projects = [{"path": str(cfg.home / "projects")}]
        roots = build_roots(cfg, projects)
    out = []
    for line in probe.probe_lines(brief):
        why = probe.check_line(line, roots)
        if why:
            out.append((line, why))
    return out


def _reason(args) -> dict:
    return {"reason": " ".join(args.reason)}


def register(sub, leaf) -> None:
    j = sub.add_parser("job", help="jobs on the board")
    js = j.add_subparsers(dest="job_cmd", metavar="ACTION")
    js.required = True

    def leafp(name, help_, func):
        p = js.add_parser(name, parents=[leaf], help=help_)
        p.set_defaults(func=func)
        return p

    p = leafp("add", "file a job (the brief must carry a DoD: line)", cmd_add)
    p.add_argument("title")
    p.add_argument("--project", required=True)
    p.add_argument("--brief", required=True, metavar="FILE|-")
    p.add_argument("--type", help="task type from catalog/types.yaml")
    p.add_argument("--parent", help="parent job id or display id (default: the project root)")
    p.add_argument("--priority", type=int, default=2, choices=range(0, 5))
    p.add_argument("--after", metavar="ID", help="claimable only once this job is verified")
    p.add_argument("--approval", action="store_true", help="file as waiting_approval")
    p.add_argument("--holdout-required", action="store_true",
                   help="claimable only once its holdout scenarios are sealed")
    p = leafp("list", "list jobs", cmd_list)
    p.add_argument("--status", default="", help="comma-separated states")
    p.add_argument("--type", default="")
    p.add_argument("--project", default="")
    p.add_argument("--tree", action="store_true", help="indent by depth, include project roots")
    p.add_argument("--self-attested", action="store_true")
    p.add_argument("--limit", type=int, default=200)
    p = leafp("show", "show one job, untruncated", cmd_show)
    p.add_argument("id")
    p.add_argument("--trail", action="store_true")
    p = leafp("search", "prior-work lookup over titles and briefs", cmd_search)
    p.add_argument("words", nargs="+")
    p.add_argument("--open", action="store_true", help="only jobs that are not finished")
    p.add_argument("--project", default="")
    leafp("claim", "claim a queued or blocked job", _verb("claim")).add_argument("id")
    for name, help_ in (("block", "block a claimed job"), ("reopen", "reopen a job"),
                        ("cancel", "cancel a job")):
        p = leafp(name, help_, _verb(name, _reason))
        p.add_argument("id")
        p.add_argument("reason", nargs="+")
    p = leafp("note", "append a note or finding to the trail", cmd_note)
    p.add_argument("id")
    p.add_argument("text", nargs="+")
    p.add_argument("--kind", choices=("note", "finding"), default="note")
    p = leafp("close", "close with evidence (VERIFY_EXIT=0 required)",
              _verb("close", lambda a: parse_evidence(a.evidence)))
    p.add_argument("id")
    p.add_argument("--evidence", required=True, metavar="FILE")
    p = leafp("review", "close a review-type job into reviewed", cmd_review)
    p.add_argument("id")
    p.add_argument("--verdict", required=True, metavar="FILE")
    p.add_argument("--done", required=True, metavar="FILE")
    p = leafp("verdict", "post a verifier verdict by hand (verifier/owner)",
              _verb("verdict", lambda a: {"verdict": a.word, "reason": " ".join(a.reason)}))
    p.add_argument("id")
    p.add_argument("word", choices=("PASS", "FAIL", "BLOCKED"))
    p.add_argument("reason", nargs="*")
    p = leafp("move", "move a job under another parent",
              _verb("move", lambda a: {"parent": a.parent, "reason": a.reason or ""}))
    p.add_argument("id")
    p.add_argument("--parent", required=True)
    p.add_argument("--reason")
    leafp("approve", "approve a waiting job (owner)", _verb("approve")).add_argument("id")
    p = leafp("lint", "check a brief's DoD before filing", cmd_lint)
    p.add_argument("file")
