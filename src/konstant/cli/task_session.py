"""Job binding for a gated session and the interactive close-out (DESIGN §6.6, docs/DSH.md).

An orchestrating session (a dsh session with the konstant-gate plugin, or any session that runs
`konstant task gate`) binds a typed task to a board job in one of three ways, first match wins:
  1. `--job N` or a `[job:N]` tag in the task text (an explicit job);
  2. `--session ID`: the open job an earlier typed message of the same session was bound to
     (`var/sessions.json`; a closed, verified, reviewed or cancelled job is not reused); with
     `--session` the bound job is also claimed when it is queued or blocked;
  3. `--file-job`: a new job filed under the session's project (the task text is the brief, so it
     must carry a `DoD:` section: the board refuses a job without one) and claimed.
`konstant task close RUN` is the close-out of an interactive run: the offline DoD check must say
MET, the job is claimed again when a verify FAIL had sent it back to `queued`, closed with the
check as its evidence, and verified by `konstant verify` (gate/loop.close_and_verify).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

from konstant.client import ClientError

JOB_TAG = re.compile(r"\[job:([0-9]+(?:\.[0-9]+)*)\]")
CLOSED = ("verified", "reviewed", "cancelled")


def job_tag(task: str):
    m = JOB_TAG.search(task or "")
    return m.group(1) if m else None


def project_for_cwd(ctx, cwd: str):
    """The slug of the board project whose path holds `cwd` (the longest match), or None."""
    if not cwd:
        return None
    here = os.path.realpath(cwd)
    try:
        rows = ctx.client("viewer").get("/api/projects")["projects"]
    except ClientError:
        return None
    best = None
    for r in rows:
        p = os.path.realpath(str(ctx.cfg.resolve(r["path"])))
        if (here == p or here.startswith(p + os.sep)) and (best is None or len(p) > len(best[1])):
            best = (r["slug"], p)
    return best[0] if best else None


def _bindings_path(ctx) -> Path:
    return Path(ctx.cfg.home) / "var" / "sessions.json"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_binding(ctx, session: str, job) -> None:
    """session -> job, written atomically under a lock (two sessions never lose a binding)."""
    path = _bindings_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{path}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _load(path)
        data[session] = {"job": str(job), "at": int(time.time())}
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(path)


def bound_job(ctx, session: str):
    """The open job this session was bound to, or None."""
    if not session:
        return None
    entry = _load(_bindings_path(ctx)).get(session)
    ref = entry.get("job") if isinstance(entry, dict) else None
    if not ref:
        return None
    try:
        job = ctx.client("viewer").get(f"/api/jobs/{ref}")
    except ClientError:
        return None
    return None if job["status"] in CLOSED else ref


def file_job(ctx, task: str, ttype: str, slug: str) -> str:
    """File + claim a job for a typed task; returns its id. The board refuses a brief without a
    DoD (exit 1 with the board's words), so a session cannot file an empty promise."""
    if not slug:
        raise ClientError("--file-job: no project for this session (run it inside a project dir, "
                          "pass --project, or name a job with [job:N])", 422)
    title = " ".join(JOB_TAG.sub(" ", task).split())[:80] or "task"
    res = ctx.client().post("/api/jobs", {"title": title, "project": slug, "brief": task,
                                          "type": ttype, "parent": "", "priority": 2,
                                          "after": "", "approval": False})
    jid = res.get("id")
    ctx.client().post(f"/api/jobs/{jid}/claim")
    print(f"konstant task: filed and claimed job {res.get('display_id', jid)} for this session",
          file=sys.stderr)
    return str(jid)


def resolve_job(ctx, task: str, ttype: str, slug: str):
    """(job ref or None, how) for a typed task: explicit, session-bound, or filed."""
    a = ctx.args
    ref = a.job or job_tag(task)
    if ref:
        how = "flag" if a.job else "tag"
    else:
        ref = bound_job(ctx, getattr(a, "session", None) or "")
        how = "session"
        if ref is None and getattr(a, "file_job", False):
            ref, how = file_job(ctx, task, ttype, slug), "filed"
    if ref and getattr(a, "session", None):
        save_binding(ctx, a.session, ref)
        _claim_open(ctx, ref)
    return (ref, how) if ref else (None, "")


def _claim_open(ctx, ref) -> None:
    """A session that works on a job holds it: a queued (or blocked) job is claimed."""
    try:
        job = ctx.client("viewer").get(f"/api/jobs/{ref}")
        if job["status"] in ("queued", "blocked"):
            ctx.client().post(f"/api/jobs/{ref}/claim")
            print(f"konstant task: claimed job {job.get('display_id', ref)} for this session",
                  file=sys.stderr)
    except ClientError as exc:
        print(f"konstant WARN: job {ref} not claimed: {exc.message}", file=sys.stderr)


def cmd_close(ctx) -> int:
    """`konstant task close RUN`: MET (offline check) -> claim if queued -> close -> verify."""
    from konstant.cli.task import _home, _resolve_run
    from konstant.gate import check as check_mod
    from konstant.gate import loop
    run = _resolve_run(ctx, ctx.args.run)
    code, lines, warns, _f = check_mod.run_check(run, None, True, home=_home(ctx))
    rec = json.loads((Path(run) / "record.json").read_text(encoding="utf-8")) if code != 5 else {}
    result = {"run": str(run), "job": rec.get("job"), "check": code, "verdict": None,
              "reasons": lines}
    if code != 0 or not rec.get("job"):
        why = ("the run has no job: nothing to close" if code == 0 else
               "the DoD check is not MET: " + "; ".join(lines))
        result["reasons"] = [why] if code == 0 else lines
        _emit(ctx, result, f"konstant task close: {why}")
        return 1 if code == 0 else code
    client = ctx.client()
    job = client.get(f"/api/jobs/{rec['job']}")
    if job["status"] in ("queued", "blocked"):
        client.post(f"/api/jobs/{rec['job']}/claim")
    verdict = {}
    rc = loop.close_and_verify(rec, client, ctx.cfg, lambda m: print(m, file=sys.stderr),
                               out=verdict)
    result.update(verdict=verdict.get("verdict"), reasons=verdict.get("reasons") or [],
                  status=client.get(f"/api/jobs/{rec['job']}").get("status"))
    _emit(ctx, result, f"konstant task close: job {rec['job']} -> {result['status']} "
          f"(verify {result['verdict']})")
    return rc


def _emit(ctx, data: dict, human: str) -> None:
    if ctx.args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(human)
