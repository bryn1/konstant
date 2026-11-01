"""The sealed store and sealing (docs/LEVEL5.md 3.2): `holdout add` and later the scenario phase
both end in `seal()`.

1. lint (holdout/lint.py) of every new file and of the set (sealed + new);
2. the negative control: every new scenario runs once on the base - the project's current HEAD
   (or, once claimed, the target commit the job clone started from), which the producer starts
   from - the way the verifier runs it (verify/holdout.py): a
   proof that already passes checks nothing (VACUOUS), a regression that fails is refused;
3. the commitment: the board stores sha256(file bytes) per scenario (POST
   /api/jobs/{id}/holdouts, owner or the scenario identity); the file becomes 0400 in a 0700 directory
   <store>/<job id>/H<n>.scenario. The SOURCE file is moved, never copied, and a source inside
   the workspace is refused (phases read the workspace).
No route serves scenario content: `holdout show` reads the store directly and is refused inside a
task run. Nothing here prints a scenario's content except `show`.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from konstant.holdout import lint
from konstant.verify import holdout as runner

STORE_DEFAULT = "var/holdout"
_HID = re.compile(r"^H([1-9][0-9]*)$")


class SealRefused(Exception):
    """`holdout add` refused; .lines are the reasons, .code the exit code (1 lint, 2 setup)."""

    def __init__(self, lines, code: int = 1):
        super().__init__("; ".join(lines))
        self.lines, self.code = list(lines), code


def root(cfg) -> Path:
    store = cfg.data["holdout"]["store"]
    if store == STORE_DEFAULT:
        return cfg.home / STORE_DEFAULT
    path = Path(os.path.realpath(store))
    home = os.path.realpath(cfg.home)
    if str(path) == home or str(path).startswith(home + os.sep):
        raise SealRefused([f"[holdout] store {store} lies inside the workspace but is not "
                           f"{STORE_DEFAULT}: only {STORE_DEFAULT} is masked in every jail"], 2)
    return path


def job_dir(cfg, job_id) -> Path:
    return root(cfg) / str(int(job_id))


def _private(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)
    return d


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(cfg, job_id, hid: str) -> bytes:
    if not _HID.match(hid):
        raise FileNotFoundError(hid)
    return (job_dir(cfg, job_id) / f"{hid}.scenario").read_bytes()


def rows(client, job) -> dict:
    return client.get(f"/api/jobs/{job}/holdouts")


def _inside(path, parent) -> bool:
    p, q = os.path.realpath(path), os.path.realpath(parent)
    return p == q or p.startswith(q + os.sep)


def prepare(cfg, job: dict, sealed: list, sources: list) -> list:
    """Parse + lint the new files against the job's brief and the sealed set. -> [(source,
    Scenario)]; SealRefused with every reason."""
    reasons, new = [], []
    for src in sources:
        if _inside(src, cfg.home):
            reasons.append(f"SOURCE INSIDE THE WORKSPACE: {src}: phases can read it; write the "
                           "scenario outside the workspace and pass that path (it is moved into "
                           "the store)")
    if reasons:
        raise SealRefused(reasons)
    nums = [int(_HID.match(r["hid"]).group(1)) for r in sealed]
    n = max(nums, default=0)
    old = []
    for r in (r for r in sealed if r["state"] == "sealed"):
        try:
            old.append(lint.parse(read(cfg, job["id"], r["hid"]), r["hid"]))
        except (OSError, lint.ScenarioError):
            reasons.append(f"holdout commitment mismatch: {r['hid']} (its store file is missing "
                           "or unreadable)")
    for src in sources:
        n += 1
        hid = f"H{n}"
        try:
            raw = lint.with_canary(Path(src).read_bytes())
            sc = lint.parse(raw, hid)
        except OSError as exc:
            reasons.append(f"UNREADABLE: {src} ({exc.strerror})")
            continue
        except lint.ScenarioError as exc:
            reasons.append(str(exc))
            continue
        reasons += lint.lint(sc, job.get("brief") or "", job.get("acceptance") or "")
        new.append((src, sc))
    reasons += lint.lint_set(old + [sc for _s, sc in new],
                             cfg.data["holdout"]["min_per_job"], str(job["id"]))
    if reasons:
        raise SealRefused(reasons)
    return new


def project_of(cfg, client, job: dict) -> Path:
    from konstant.verify.verifier import project_dir
    path = project_dir(cfg, client.get("/api/projects")["projects"], job["project"])
    if path is None or not (Path(path) / ".git").exists():
        raise SealRefused([f"job {job['id']}'s project {job['project']} is not a git repository: "
                           "holdouts run on a commit"], 2)
    return Path(path)


def seal(cfg, client, ref: str, sources: list) -> list:
    """The whole of 3.2 for `holdout add`. Returns the board's rows of the new scenarios."""
    why = runner.confined(cfg)
    if why:
        raise SealRefused([why + " (the negative control runs every scenario in it)"], 2)
    job = client.get(f"/api/jobs/{ref}")
    if job["status"] not in ("queued", "waiting_approval"):
        raise SealRefused([f"job {job['display_id']} is {job['status']}: holdouts are sealed "
                           "only while the job is not claimed (queued or waiting_approval)"])
    sealed = rows(client, job["id"])["holdouts"]
    new = prepare(cfg, job, sealed, [Path(s) for s in sources])
    project = project_of(cfg, client, job)
    try:   # the base: the target commit the job clone starts from (LEVEL5 3.2 step 2, 2.4)
        base = runner.resolve(project, job.get("workdir_base") or "HEAD")
        control = runner.negative_control(cfg, [sc for _s, sc in new], project, base)
    except runner.HoldoutError as exc:
        raise SealRefused([str(exc)], 2)
    if control:
        raise SealRefused(control)
    d = _private(job_dir(cfg, job["id"]))
    _private(d.parent)
    staged = []
    try:
        for _src, sc in new:
            tmp = d / f".{sc.hid}.staged"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
            with os.fdopen(fd, "wb") as fh:
                fh.write(sc.raw)
            staged.append((tmp, d / f"{sc.hid}.scenario"))
        res = client.post(f"/api/jobs/{job['id']}/holdouts", {"holdouts": [
            {"hid": sc.hid, "kind": sc.kind, "sha256": sha256(sc.raw)} for _s, sc in new]})
    except BaseException:
        for tmp, _final in staged:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, final in staged:
        os.replace(tmp, final)
    for src, _sc in new:
        os.unlink(src)                         # moved: no copy stays outside the store
    return res["holdouts"]


def check(cfg, client, ref: str, control: bool = False) -> list:
    """(hid, status) for each sealed scenario: the commitment, the parse and, with control, the
    negative control on the project's current HEAD. Content is never printed."""
    job = client.get(f"/api/jobs/{ref}")
    out, parsed = [], []
    for r in rows(client, job["id"])["holdouts"]:
        if r["state"] != "sealed":
            out.append((r["hid"], r["state"]))
            continue
        try:
            raw = read(cfg, job["id"], r["hid"])
        except OSError:
            out.append((r["hid"], "MISSING: holdout commitment mismatch"))
            continue
        if sha256(raw) != r["sha256"]:
            out.append((r["hid"], "MISMATCH: holdout commitment mismatch"))
            continue
        try:
            parsed.append(lint.parse(raw, r["hid"]))
            out.append((r["hid"], "ok"))
        except lint.ScenarioError as exc:
            out.append((r["hid"], str(exc)))
    if control and parsed:
        project = project_of(cfg, client, job)
        base = runner.resolve(project, "HEAD")
        bad = {line.split(":", 1)[1].split()[0]: line
               for line in runner.negative_control(cfg, parsed, project, base)}
        out = [(h, bad.get(h, s)) for h, s in out]
    return out


def doctor_row(cfg) -> tuple:
    """Which separation the holdout store has (docs/LEVEL5.md 3.8, owner question Q3)."""
    why = runner.confined(cfg)
    try:
        where = root(cfg)
    except SealRefused as exc:
        return ("FAIL", "holdouts", exc.lines[0])
    if why:
        return ("INFO", "holdouts", f"{why}: a job with sealed holdouts does not run, and "
                "`holdout add` refuses (no negative control without the jail)")
    if where == cfg.home / STORE_DEFAULT:
        return ("INFO", "holdouts", f"store {STORE_DEFAULT}/: masked in every jailed phase and "
                "read-denied by every adapter; one OS user, so a process you run unjailed can "
                "read it (for more, [holdout] store outside the workspace under a second OS "
                "user who runs the verifier)")
    return ("INFO", "holdouts", f"store {where} outside the workspace: give it to the OS user "
            "that runs `konstant verify` alone")
