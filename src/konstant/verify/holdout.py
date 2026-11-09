"""Running holdouts (docs/LEVEL5.md 3.6): only konstant's own code runs them, never a phase.

1. The tree of the pinned commit is MATERIALISED by konstant from `ls-tree` / `cat-file` into a
   private temp dir: no checkout, no filter, no hook, no attribute runs (F-04). The run is
   pinned to the closed commit, not to whatever the live tree holds (F-28 for holdouts).
2. Each RUN executes as an argv (no shell) in konstant.jail with NO network; the only writable
   binds are that temp dir, bound at the project's own path (the code under test sees the path
   the tests rule shows it), and a private TMPDIR; var/secrets/ and the sealed store are masked;
   the env is scrubbed; the timeout is [holdout] run_timeout_s.
3. The temp dir is deleted afterwards: nothing a scenario run writes persists.
The expectation never enters the jail: stdout and the exit code are matched here, outside it.
A result row holds the scenario id, pass/fail and timings, never a command or an output.
`evaluate` is the verifier's step (commitment, claim order, leak scan, the runs); `negative_control`
is the same run on the base that `holdout add` uses (3.2 step 2). Without a working jail nothing
runs: holdouts need a confined phase (fail closed).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from konstant import jail as jail_mod
from konstant.gate.rules.common import GIT_ISOLATION
from konstant.holdout import lint
from konstant.verify.procenv import git_env, scrub_env

UNCONFINED = "holdouts need a confined phase"


class HoldoutError(Exception):
    """A holdout set that cannot be run (no jail, no tree): BLOCKED, never a guess."""


def _git(project, *args, data: bytes | None = None, timeout: int = 120):
    return subprocess.run(["git", *GIT_ISOLATION, "-C", str(project), *args], input=data,
                          capture_output=True, env=git_env(), timeout=timeout)


def resolve(project, rev: str) -> str:
    r = _git(project, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}")
    sha = r.stdout.decode().strip()
    if r.returncode != 0 or not sha:
        raise HoldoutError(f"commit {rev} is not in the project repository")
    return sha


# git features that make the objects a plumbing read sees differ from the real commit: a replace
# ref swaps one object for another, a graft or shallow file rewrites a commit's parents. Every git
# konstant runs sets GIT_NO_REPLACE_OBJECTS=1 and grafts are off, but a clone that CARRIES them is
# refused outright, so `verified` can never name a commit whose real tree failed (REVIEW L5-R1
# H-02); the clone is konstant's own (factory/clone.py: no replace ref, no graft).
def git_dir(project) -> str:
    r = _git(project, "rev-parse", "--git-dir")
    d = r.stdout.decode().strip()
    if r.returncode != 0 or not d:
        raise HoldoutError(f"{project} is not a git repository")
    return d if os.path.isabs(d) else os.path.join(str(project), d)


def refuse_rewrites(project) -> None:
    """Raise HoldoutError when `project`'s .git carries a replace ref, a graft or a shallow file:
    they would let a read see a different tree than the commit's real objects."""
    gd = git_dir(project)
    r = _git(project, "for-each-ref", "--format=%(refname)", "refs/replace/")
    refs = [x for x in r.stdout.decode().splitlines() if x.strip()]
    if refs:
        raise HoldoutError(f"the repository carries replace ref(s) ({', '.join(refs[:3])}): "
                           "konstant refuses it (a replace ref makes the verified objects differ "
                           "from the commit's real tree)")
    for rel in ("info/grafts", "shallow"):
        if os.path.exists(os.path.join(gd, rel)):
            raise HoldoutError(f"the repository carries {rel}: konstant refuses it (it rewrites "
                               "which objects a commit reaches)")


def tree(project, commit: str) -> list:
    """[(mode, oid, path)] of every blob of the commit (plumbing: ls-tree)."""
    r = _git(project, "ls-tree", "-r", "-z", "--full-tree", commit)
    if r.returncode != 0:
        raise HoldoutError(f"cannot list the tree of {commit}")
    out = []
    for item in r.stdout.split(b"\0"):
        if not item:
            continue
        meta, _, path = item.partition(b"\t")
        mode, kind, oid = meta.decode().split()
        if kind == "blob":
            out.append((mode, oid, path.decode("utf-8", "surrogateescape")))
    return out


def blobs(project, oids: list) -> dict:
    """{oid: bytes} through one `cat-file --batch` (raw objects: no textconv, no filter)."""
    if not oids:
        return {}
    r = _git(project, "cat-file", "--batch", data="".join(o + "\n" for o in oids).encode())
    if r.returncode != 0:
        raise HoldoutError("cannot read the blobs of the commit")
    out, buf, i = {}, r.stdout, 0
    for oid in oids:
        nl = buf.index(b"\n", i)
        head = buf[i:nl].split()
        if len(head) != 3 or head[1] != b"blob":
            raise HoldoutError(f"object {oid} is not a blob")
        size = int(head[2])
        out[oid] = buf[nl + 1:nl + 1 + size]
        i = nl + 1 + size + 1
    return out


def materialise(project, commit: str, dest: Path) -> None:
    """Write the commit's tree into `dest` from raw objects. Symlinks are created, never followed;
    a path that would leave `dest` is refused."""
    entries = tree(project, commit)
    data = blobs(project, list(dict.fromkeys(o for _m, o, _p in entries)))
    root = os.path.realpath(dest)
    for mode, oid, rel in entries:
        if rel.startswith("/") or ".." in rel.split("/"):
            raise HoldoutError(f"tree path {rel!r} leaves the tree")
        if ".git" in (p.lower() for p in rel.split("/")):
            raise HoldoutError(f"tree path {rel!r} writes into a .git directory")
        target = os.path.join(root, rel)
        parent = os.path.dirname(target)
        os.makedirs(parent, exist_ok=True)
        if os.path.realpath(parent) != parent:
            raise HoldoutError(f"tree path {rel!r} runs through a symlink")
        if mode == "120000":
            os.symlink(data[oid], target)
            continue
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o755 if mode == "100755" else 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data[oid])


def confined(cfg) -> str | None:
    """Why no holdout can run here (None: the jail works)."""
    if not cfg.data["gate"]["jail"]:
        return f"{UNCONFINED}: [gate] jail = false"
    if not cfg.confinement().integrity:
        return (f"{UNCONFINED}: [confinement] integrity = \"off\" (factory mode never starts "
                "without the integrity core: docs/CONCEPTS.md \"Confinement profiles\")")
    if not jail_mod.available():
        return f"{UNCONFINED}: konstant's jail (bubblewrap) is unavailable" + \
            (" (KONSTANT_NO_JAIL=1)" if os.environ.get("KONSTANT_NO_JAIL") == "1" else "")
    return None


def runnable(exe: str, tree_dir: Path) -> bool:
    """The program exists: on PATH, or (a path) inside the materialised tree or absolute. The
    jail's own exit code cannot say "not found" apart from the product's own exit 1."""
    if "/" not in exe:
        return shutil.which(exe, path=scrub_env().get("PATH", os.defpath)) is not None
    p = exe if os.path.isabs(exe) else os.path.join(tree_dir, exe)
    return os.path.isfile(p) and os.access(p, os.X_OK)


def run_one(sc, tree_dir: Path, project: Path, home, timeout: float) -> dict:
    """One scenario in the jail, no network, at the project's path. Never raises for the
    product's behaviour; HoldoutError when the jail would not wrap it."""
    t0 = time.time()
    if not runnable(sc.argv()[0], tree_dir):
        return {"hid": sc.hid, "kind": sc.kind, "passed": False, "unrunnable": True,
                "timed_out": False, "net": False, "duration_s": 0.0}
    with jail_mod.session(sc.argv(), home=home, cwd=project, net=False,
                          env={**scrub_env(), "PYTHONNOUSERSITE": "1"},
                          binds=[(tree_dir, project)]) as (argv, env):
        if argv[:1] == sc.argv()[:1]:
            raise HoldoutError(f"{UNCONFINED}: the jail did not wrap the run")
        # a private HOME: nothing a phase planted under the user's home (a Python usercustomize,
        # a ~/.node_modules, an rc file) loads into the program a scenario runs (REVIEW H-01)
        env["HOME"] = env.get("TMPDIR") or env.get("HOME", "/")
        env.pop("XDG_CONFIG_HOME", None)
        env.pop("XDG_DATA_HOME", None)
        proc = subprocess.Popen(argv, cwd=str(project), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        timed_out = False
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, _ = proc.communicate()
    rc = proc.returncode
    unrunnable = timed_out or rc in (126, 127)
    passed = not unrunnable and lint.matches(sc, rc, (out or b"").decode("utf-8", "replace"))
    return {"hid": sc.hid, "kind": sc.kind, "passed": passed, "unrunnable": unrunnable,
            "timed_out": timed_out, "net": False, "duration_s": round(time.time() - t0, 3)}


def run_set(cfg, scenarios: list, project: Path, commit: str) -> list:
    """Materialise `commit` once and run every scenario on it; rows carry `commit`."""
    why = confined(cfg)
    if why:
        raise HoldoutError(why)
    refuse_rewrites(project)
    tmp = Path(tempfile.mkdtemp(prefix="konstant-holdout-"))
    try:
        materialise(project, commit, tmp)
        timeout = cfg.data["holdout"]["run_timeout_s"]
        return [{**run_one(sc, tmp, Path(project), cfg.home, timeout), "commit": commit}
                for sc in scenarios]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def negative_control(cfg, scenarios: list, project: Path, base: str) -> list:
    """3.2 step 2: refusal lines for scenarios that check nothing on the base."""
    out = []
    for row in run_set(cfg, scenarios, project, base):
        if row["unrunnable"]:
            out.append(f"UNRUNNABLE: {row['hid']} could not run on the base "
                       f"({'timeout' if row['timed_out'] else 'command not found or not runnable'})")
        elif row["kind"] == "proof" and row["passed"]:
            out.append(f"VACUOUS: {row['hid']} passes before the work")
        elif row["kind"] == "regression" and not row["passed"]:
            out.append(f"REGRESSION FAILS: {row['hid']} fails before the work (a regression "
                       "scenario must pass on the base)")
    return out


def digest(rows: list) -> str:
    """The commitment digest of a set: sha256 over `hid:sha256` lines, sorted."""
    text = "\n".join(sorted(f"{r['hid']}:{r['sha256']}" for r in rows))
    return hashlib.sha256(text.encode()).hexdigest()


# --- the verifier's step (3.5 + 3.6) ---------------------------------------------------------

def _claim_trail_id(trail: list):
    """The trail id of the claim that started the round being judged (the newest claim)."""
    ids = [t["id"] for t in trail if t.get("kind") == "status"
           and str(t.get("body", "")).startswith("claimed by ")]
    return max(ids) if ids else None


def evaluate(client, cfg, job: dict, projects: list) -> dict | None:
    """None for a job without holdouts; else the holdout result settle() reads:
    rows (id, kind, pass/fail, commit, net, timings), failed [(hid, hint)], leak, suspect,
    integrity (commitment mismatch / LEAK: BLOCKED first), blocked (unrunnable: BLOCKED)."""
    from konstant.holdout import leak, store
    from konstant.verify.verifier import job_dir
    if not job.get("holdout_required"):         # sealing marks the job; level 4 is unchanged
        return None
    all_rows = store.rows(client, job["id"])["holdouts"]
    min_n = cfg.data["holdout"]["min_per_job"]
    current = [r for r in all_rows if r["state"] == "sealed"]
    burned = [r for r in all_rows if r["state"] == "burned"]
    res = {"rows": [], "failed": [], "leak": [], "suspect": [], "integrity": [], "blocked": [],
           "commit": None, "digest": digest(current) if current else None,
           "generation": max((r["generation"] for r in current), default=None),
           "sealed": len(current), "min_per_job": min_n}
    scenarios, mismatch = {}, []
    for r in current + burned:
        try:
            raw = store.read(cfg, job["id"], r["hid"])
        except OSError:
            mismatch.append(r["hid"])
            continue
        if store.sha256(raw) != r["sha256"]:
            mismatch.append(r["hid"])
            continue
        try:
            scenarios[r["hid"]] = (r, lint.parse(raw, r["hid"]))
        except lint.ScenarioError:
            mismatch.append(r["hid"])
    if mismatch:
        res["integrity"].append(f"holdout commitment mismatch: {', '.join(mismatch)} (the store "
                                "changed after sealing)")
        return res
    if burned and not current:
        res["integrity"].append("the job's holdout set is burned (a LEAK was found): the owner "
                                "reopens the job with a fresh set, or cancels it")
        return res
    ev = job.get("evidence") or {}
    commit = (ev.get("commit") or "").strip()
    project = job_dir(cfg, projects, job)       # the job clone when the board recorded one
    trail = client.get(f"/api/jobs/{job['id']}/trail")["trail"]
    runs = [r.get("run_dir") for r in job.get("runs") or [] if r.get("run_dir")]
    if project is None or not (Path(project) / ".git").exists():
        res["blocked"].append("holdouts run on a commit: the job's project is not a git "
                              "repository")
        return res
    if not commit:
        res["blocked"].append("the evidence names no COMMIT=: holdouts run only on the commit "
                              "the job closed with")
        return res
    try:
        refuse_rewrites(project)
        commit = resolve(project, commit)
        base = (ev.get("base") or "").strip()
        base = resolve(project, base) if base else None
        res["commit"] = commit
        leaks, suspects = leak.scan(cfg.home, [scenarios[r["hid"]][1] for r in current],
                                    project=project, base=base, commit=commit, runs=runs,
                                    trail=trail, brief=job.get("brief") or "")
        mem_leaks, mem_suspects = leak.memory_findings(trail)
        leaks, suspects = leaks + mem_leaks, suspects + mem_suspects
    except HoldoutError as exc:
        res["blocked"].append(f"holdouts not run: {exc}")
        return res
    if leaks:
        res["leak"], res["integrity"] = leaks, list(leaks)
        return res
    if len(current) < min_n:
        res["blocked"].append(f"{len(current)} sealed holdout(s), [holdout] min_per_job = {min_n}")
        return res
    claim = _claim_trail_id(trail)
    late = [r["hid"] for r in current if claim is None or (r.get("trail_id") or 0) > claim]
    if late:
        res["blocked"].append(f"holdout(s) {', '.join(late)} were not sealed before the claim of "
                              "the round being judged")
        return res
    try:
        rows = run_set(cfg, [scenarios[r["hid"]][1] for r in current], Path(project), commit)
    except HoldoutError as exc:
        res["blocked"].append(f"holdouts not run: {exc}")
        return res
    for row in rows:
        hint = scenarios[row["hid"]][1].hint
        if row["unrunnable"]:
            res["blocked"].append(f"holdout {row['hid']} could not run ("
                                  + ("timeout" if row["timed_out"] else "not runnable") + ")")
        elif not row["passed"]:
            res["failed"].append((row["hid"], hint))
        res["rows"].append({k: row[k] for k in ("hid", "kind", "passed", "commit", "net",
                                                "duration_s", "timed_out")}
                           | ({"hint": hint} if not row["passed"] else {}))
    res["suspect"] = suspects
    return res


def reasons(res: dict) -> tuple:
    """(integrity, fail, blocked) reason lines - redacted: ids and hints only (3.6 step 5)."""
    fail = [f"holdout {h} failed (hint: {hint})" for h, hint in res["failed"]] + res["suspect"]
    return list(res["integrity"]), fail, list(res["blocked"])


def public(res: dict | None) -> dict | None:
    """What leaves the verifier (verifications.holdout_json, `verify --json`): ids, pass/fail,
    timings, the commit and the commitment digest; never a command, an expectation or output."""
    if res is None:
        return None
    return {"rows": res["rows"], "commit": res["commit"], "digest": res["digest"],
            "generation": res["generation"], "sealed": res["sealed"],
            "min_per_job": res["min_per_job"], "net": False,
            "failed": [h for h, _hint in res["failed"]], "leak": bool(res["leak"]),
            "suspect": bool(res["suspect"]),
            "mismatch": any("commitment mismatch" in x for x in res["integrity"]),
            "failed_round": bool(res["failed"] or res["suspect"])}
