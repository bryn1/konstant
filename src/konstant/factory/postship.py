"""Post-ship checks (docs/LEVEL5.md 5.3): after the target moved, the shipped state must hold.

For the github and branch targets, on the target's new tip (github: the merge GitHub made):
  1. `merged` (github): the verified commit is an ancestor of the new tip and the tip's tree is the
     verified commit's tree (the shipped state is exactly what was verified);
  2. `probe`: the goal's post_probes and the job's own DoD probes, `{workdir}` = the target
     (whose worktree konstant just rewrote to the tip from raw objects), through the probe
     allowlist (verify/probe.py run_line);
  3. `tests`: the project's own test command ([gate] test_cmd; `auto` = pytest when the tree
     holds tests) in konstant's jail, no network, on the tip MATERIALISED by konstant into a
     private dir bound at the target's own path;
  4. `regression`: every sealed holdout of every job shipped so far in this project, and of this
     job, on a fresh materialisation of the tip, the way the verifier runs them (commitments
     checked first; findings redacted to ids and hints).
apply and command targets run the probes only (`{workdir}` = the apply dir / the target).
A check that cannot run counts as failed: any failure rolls the ship back.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from konstant.factory import shiprepo


def _row(name: str, ok: bool, reason: str, **extra) -> dict:
    return {"check": name, "ok": bool(ok), "reason": reason, **extra}


def _materialised(repo, tip: str) -> Path:
    from konstant.verify.holdout import materialise
    tmp = Path(tempfile.mkdtemp(prefix="konstant-postship-"))
    materialise(repo, tip, tmp)
    return tmp


def probes(cfg, client, conf: dict, job: dict, workdir) -> list:
    from konstant.verify import probe as probe_mod
    from konstant.verify.verifier import build_roots, workdir_text
    projects = client.get("/api/projects")["projects"]
    roots = build_roots(cfg, projects)
    roots.paths.append(Path(workdir))
    wd = workdir_text(cfg, workdir)
    items = [(p, probe_mod.with_workdir(p, wd)) for p in conf["post_probes"]]
    items += [(None, ln) for ln in probe_mod.probe_lines(
        probe_mod.with_workdir(job.get("acceptance") or "", wd))]
    out, seen = [], set()
    for raw, line in items:
        if line in seen:
            continue
        seen.add(line)
        row = probe_mod.run_line(line, roots, "post", cfg.data["verify"]["probe_timeout_s"])
        kind = probe_mod.verdict_of(row)
        out.append(_row("probe", kind == "matched", f"{line} -> {kind}"
                        + (f" ({row['error']})" if row.get("error") else ""),
                        **({"line": raw} if raw else {})))
    return out


def tests(cfg, repo, tip: str, target: Path) -> dict:
    from konstant import jail
    from konstant.gate.rules.tests import project_has_tests, pytest_argv
    from konstant.verify.procenv import scrub_env
    cmd = cfg.data["gate"]["test_cmd"]
    tmp = _materialised(repo, tip)
    try:
        if cmd == "auto":
            if not project_has_tests(tmp, tmp / ".no-out"):
                return _row("tests", True, "the project has no tests of its own")
            argv = pytest_argv(["--rootdir", target, target])
        else:
            import shlex
            argv = shlex.split(cmd)
        env = {**scrub_env(), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        try:
            with jail.session(argv, home=cfg.home, cwd=target, net=False, env=env,
                              binds=[(tmp, target)]) as (run, run_env):
                if run[:1] == argv[:1]:
                    return _row("tests", False, "the project tests need konstant's jail")
                r = subprocess.run(run, cwd=str(target), capture_output=True, text=True,
                                   timeout=1800, env=run_env, stdin=subprocess.DEVNULL,
                                   errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _row("tests", False, f"the project tests could not run ({exc})")
        good = r.returncode in ((0, 5) if cmd == "auto" else (0,))
        return _row("tests", good, f"project tests exit {r.returncode} on the shipped tip")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def shipped_jobs(client, job_id: int, project: str) -> list:
    """This job and every job of the same project whose ship still stands (state shipped)."""
    out = [job_id]
    for s in client.get("/api/ships")["ships"]:
        if s["state"] == "shipped" and s["job_id"] not in out and s.get("post"):
            j = client.get(f"/api/jobs/{s['job_id']}")
            if j.get("project") == project:
                out.append(s["job_id"])
    return out


def regression(cfg, client, repo, tip: str, target: Path, job: dict) -> list:
    from konstant.holdout import lint, store
    from konstant.verify import holdout as runner
    rows, scenarios = [], []
    for jid in shipped_jobs(client, job["id"], job["project"]):
        for r in store.rows(client, jid)["holdouts"]:
            if r["state"] != "sealed":
                continue
            try:
                raw = store.read(cfg, jid, r["hid"])
            except OSError:
                rows.append(_row("regression", False, f"holdout {r['hid']} of job {jid} is "
                                 "missing from the store"))
                continue
            if store.sha256(raw) != r["sha256"]:
                rows.append(_row("regression", False, f"holdout commitment mismatch: {r['hid']} "
                                 f"of job {jid}"))
                continue
            scenarios.append((jid, lint.parse(raw, r["hid"])))
    why = runner.confined(cfg)
    if why:
        return rows + [_row("regression", False, why)]
    tmp = _materialised(repo, tip)
    try:
        for jid, sc in scenarios:
            res = runner.run_one(sc, tmp, target, cfg.home, cfg.data["holdout"]["run_timeout_s"])
            if res["passed"]:
                rows.append(_row("regression", True, f"holdout {sc.hid} of job {jid} passed"))
            else:
                what = "could not run" if res["unrunnable"] else f"failed (hint: {sc.hint})"
                rows.append(_row("regression", False, f"holdout {sc.hid} of job {jid} {what}"))
    except runner.HoldoutError as exc:
        rows.append(_row("regression", False, f"holdouts not run: {exc}"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rows


def run(cfg, client, tgt, job: dict, conf: dict, commit: str, tip: str) -> dict:
    """Every post-ship check for the shipped `tip`; {"ok", "checks", "failed", "failed_probes"}."""
    checks = []
    repo, target = tgt.repo, tgt.target
    try:
        if tgt.name == "github":
            same = shiprepo.is_ancestor(repo, commit, tip) and \
                shiprepo.tree_of(repo, tip) == shiprepo.tree_of(repo, commit)
            checks.append(_row("merged", same, "the merged tip's tree is the verified commit's"
                               if same else "the merged tip is not the verified commit's tree"))
            err = getattr(tgt, "local_error", "")
            if err:
                checks.append(_row("merged", False, f"the local target did not move: {err}"))
        checks += probes(cfg, client, conf, job, tgt.workdir())
        if tgt.name in ("github", "branch"):
            checks.append(tests(cfg, repo, tip, target))
            checks += regression(cfg, client, repo, tip, target, job)
    except Exception as exc:  # noqa: BLE001 - a check that cannot run is a failed check
        print(f"konstant ship: a post-ship check could not run: {exc}", file=sys.stderr)
        checks.append(_row("internal", False, f"a post-ship check could not run: "
                           f"{type(exc).__name__}"))
    failed = [c for c in checks if not c["ok"]]
    return {"ok": not failed, "checks": checks,
            "failed": [c["reason"] for c in failed],
            "failed_probes": [c["line"] for c in failed if c["check"] == "probe" and c.get("line")]}
