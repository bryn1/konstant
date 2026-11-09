"""Ship targets (docs/LEVEL5.md 5.1): where a verified commit goes and how it comes back.

Every target works from the ship repository (factory/shiprepo.py), never from the job clone:

  github   push the commit to `konstant/ship-<n>` of [ship] remote, `gh pr create` into the
           branch, `gh pr merge --merge --match-head-commit <commit>` (GitHub refuses a head that
           moved), fetch the branch back: its new tip is the shipped state. Rollback: a commit
           whose tree is the pre-ship tree on top of that tip, pushed as `konstant/rollback-<n>`
           and merged through its own pull request; never a force-push, never a branch delete.
  branch   copy the objects into the target and `update-ref refs/heads/<branch> <commit> <pre>`
           (compare-and-swap). Rollback: the same revert commit, CAS again.
  apply    materialise the commit into [ship] apply_dir, keeping the previous tree beside it as
           `<apply_dir>.prev`. Rollback: swap it back.
  command  the owner's ship_cmd / rollback_cmd ({commit}, {branch}, {job}), argv split, no shell.

For github and branch the local target (the project the job clone was made from) moves too, so the
next job's clone starts from the shipped state. When its checked-out branch is the ship branch,
konstant rewrites the changed paths of its worktree itself from raw objects (no checkout, filter or
hook) after the CAS, and refuses a worktree with local changes on those paths.
Nothing here decides whether to ship: factory/ship.py runs the guard first.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from konstant.factory import shiprepo
from konstant.factory.localtarget import local_checks, local_tip, move_local
from konstant.factory.shiprepo import ShipRepoError


class TargetRefused(Exception):
    """The target refused the ship and was left as it was (an owner decision)."""


class RollbackFailed(Exception):
    """The rollback did not leave the target at the pre-ship tree: shipping halts."""


GH_ENV = ("HOME", "LANG", "LC_ALL", "GH_TOKEN", "GITHUB_TOKEN", "GH_HOST", "GH_CONFIG_DIR",
          "GH_ENTERPRISE_TOKEN", "XDG_CONFIG_HOME", "SSH_AUTH_SOCK")


def own_env() -> dict:
    """The environment of the ship's push and gh calls: the factory process's own credentials
    (HOME for ~/.config/gh, the gh token variables, the ssh agent) and konstant's trusted PATH.
    It never depends on a phase's environment: phases never run this code."""
    from konstant import tools
    env = {k: os.environ[k] for k in GH_ENV if os.environ.get(k)}
    env.update(PATH=tools.trusted_path(), GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1",
               NO_COLOR="1", GIT_TERMINAL_PROMPT="0")
    return env


class Base:
    name = ""

    def __init__(self, cfg, conf: dict, target: Path, repo: Path, job: dict, pre: str):
        self.cfg, self.conf, self.target, self.repo = cfg, conf, Path(target), Path(repo)
        self.job, self.pre, self.branch = job, pre, conf["branch"]
        self.ref = f"refs/heads/{self.branch}"

    def precheck(self) -> list:
        return []

    def workdir(self) -> Path:
        """What `{workdir}` names in the post-ship probes: the shipped state on disk."""
        return self.target


def revert_commit(repo: Path, pre: str, tip: str, n: int) -> str:
    return shiprepo.commit_tree(repo, shiprepo.tree_of(repo, pre), [tip],
                                f"konstant: roll back ship {n}")


# --- branch ----------------------------------------------------------------------------------

class BranchTarget(Base):
    name = "branch"

    def precheck(self) -> list:
        paths = [r[1] for r in shiprepo.changes(self.repo, self.pre, self.job["commit"])]
        return local_checks(self.target, self.ref, self.pre, paths)

    def ship(self, n: int, commit: str) -> str:
        try:
            move_local(self.repo, self.target, self.ref, self.pre, commit)
        except ShipRepoError as exc:
            raise TargetRefused(str(exc)) from None
        return commit

    def rollback(self, n: int, tip: str) -> str:
        try:
            rb = revert_commit(self.repo, self.pre, tip, n)
            move_local(self.repo, self.target, self.ref, tip, rb)
            now = local_tip(self.target, self.ref)
        except (ShipRepoError, OSError) as exc:
            raise RollbackFailed(str(exc)) from None
        if shiprepo.tree_of(self.target, now) != shiprepo.tree_of(self.repo, self.pre):
            raise RollbackFailed(f"{self.ref} tree is not the pre-ship tree after the rollback")
        return now


# --- github ------------------------------------------------------------------------------------

class GithubTarget(Base):
    name = "github"
    TRACK = "refs/konstant/remote/"

    def gh(self) -> str:
        from konstant import tools
        exe = self.conf["gh"] or tools.which("gh") or ""
        return exe if exe and os.path.isfile(exe) and os.access(exe, os.X_OK) else ""

    def _net(self) -> tuple:
        url = self.conf["remote"]
        extra = shiprepo.NET
        if url.startswith("https://") and self.gh():
            extra += ("-c", f"credential.helper=!{shlex.quote(self.gh())} auth git-credential")
        return extra

    def _env(self) -> dict:
        from konstant import tools
        env = own_env()
        url = self.conf["remote"]
        if url.startswith(("ssh://", "git@")) and tools.which("ssh"):
            env["GIT_SSH_COMMAND"] = f"{tools.which('ssh')} -o BatchMode=yes"
        return env

    def fetch(self) -> str:
        track = self.TRACK + self.branch
        r = shiprepo.run(self.repo, "fetch", "--no-tags", "--no-write-fetch-head", "-q",
                         self.conf["remote"], f"+{self.ref}:{track}", net=self._net(),
                         env=self._env(), timeout=600)
        if r.returncode != 0:
            raise ShipRepoError("fetch of the remote branch failed: "
                                + r.stderr.decode("utf-8", "replace").strip()[-300:])
        return shiprepo.out(self.repo, "rev-parse", "--verify", "-q", track)

    def push(self, sha: str, branch: str) -> None:
        r = shiprepo.run(self.repo, "push", "--porcelain", "--no-verify", self.conf["remote"],
                         f"{sha}:refs/heads/{branch}", net=self._net(), env=self._env(),
                         timeout=600)
        if r.returncode != 0:
            raise ShipRepoError(f"push of {branch} refused: "
                                + (r.stderr or r.stdout).decode("utf-8", "replace").strip()[-300:])

    def gh_run(self, *args) -> str:
        r = subprocess.run([self.gh(), *args, "--repo", self.conf["github_repo"]],
                           capture_output=True, text=True, env=own_env(), timeout=600,
                           stdin=subprocess.DEVNULL, cwd=str(self.repo))
        if r.returncode != 0:
            raise ShipRepoError(f"gh {args[0]} {args[1]} refused: "
                                + (r.stderr or r.stdout).strip()[-300:])
        return r.stdout.strip()

    def pull_request(self, sha: str, head: str, title: str) -> str:
        url = self.gh_run("pr", "create", "--base", self.branch, "--head", head, "--title", title,
                          "--body", f"{title}\n\nOpened by konstant's ship step for the commit "
                          f"{sha}, which the verifier passed with every holdout.")
        number = url.rstrip("/").rsplit("/", 1)[-1]
        if not number.isdigit():
            raise ShipRepoError(f"gh pr create printed no pull request URL ({url[-120:]})")
        self.gh_run("pr", "merge", number, "--merge", "--match-head-commit", sha)
        return number

    def precheck(self) -> list:
        from konstant.factory.shiprules import bad, ok
        if not self.conf["github_repo"] or not self.conf["remote"]:
            return [bad("target", "the github target needs [ship] github_repo (OWNER/REPO)")]
        if not self.gh():
            return [bad("target", "no gh CLI: set [ship] gh to its absolute path (konstant does "
                                  "not take gh from PATH)")]
        try:
            remote = self.fetch()
        except ShipRepoError as exc:
            return [bad("base", f"target moved: expected {self.pre}, the remote cannot be read "
                                f"({exc})")]
        if remote != self.pre:
            return [bad("base", f"target moved: expected {self.pre}, the remote {self.branch} is "
                                f"at {remote}")]
        paths = [r[1] for r in shiprepo.changes(self.repo, self.pre, self.job["commit"])]
        return [ok("remote", f"the remote {self.branch} is at {self.pre[:12]}")] + \
            local_checks(self.target, self.ref, self.pre, paths)

    def ship(self, n: int, commit: str) -> str:
        try:
            self.push(commit, f"konstant/ship-{n}")
            self.pull_request(commit, f"konstant/ship-{n}",
                              f"konstant: ship job {self.job['display_id']} (ship {n})")
            tip = self.fetch()
        except ShipRepoError as exc:
            raise TargetRefused(f"target refused: {exc}") from None
        try:
            move_local(self.repo, self.target, self.ref, self.pre, tip)
        except ShipRepoError as exc:
            self.local_error = str(exc)
        return tip

    def rollback(self, n: int, tip: str) -> str:
        try:
            rb = revert_commit(self.repo, self.pre, tip, n)
            self.push(rb, f"konstant/rollback-{n}")
            self.pull_request(rb, f"konstant/rollback-{n}", f"konstant: roll back ship {n}")
            now = self.fetch()
        except (ShipRepoError, OSError) as exc:
            raise RollbackFailed(str(exc)) from None
        if shiprepo.tree_of(self.repo, now) != shiprepo.tree_of(self.repo, self.pre):
            raise RollbackFailed(f"the remote {self.branch} tree is not the pre-ship tree after "
                                 "the rollback")
        try:
            have = local_tip(self.target, self.ref)
            move_local(self.repo, self.target, self.ref, have, now)
        except ShipRepoError as exc:
            raise RollbackFailed(f"the remote is rolled back; the local target is not: {exc}") \
                from None
        return now


# --- apply / command -------------------------------------------------------------------------

class ApplyTarget(Base):
    name = "apply"

    def dirs(self):
        d = self.cfg.resolve(self.conf["apply_dir"])
        return d, Path(str(d) + ".prev"), Path(str(d) + ".new")

    def workdir(self) -> Path:
        return self.dirs()[0]

    def precheck(self) -> list:
        from konstant.factory.shiprules import bad, ok
        if not self.conf["apply_dir"]:
            return [bad("target", "the apply target needs [ship] apply_dir")]
        from konstant import machinery
        real = os.path.realpath(self.dirs()[0])
        core = [*machinery.dirs(self.cfg.home), self.cfg.home / "var", self.target]
        for c in core:
            c = os.path.realpath(c)
            if real == c or real.startswith(c + os.sep) or c.startswith(real + os.sep):
                return [bad("target", f"[ship] apply_dir {self.conf['apply_dir']} overlaps "
                                      f"{c}: konstant's machinery and the project are not "
                                      "apply targets")]
        return [ok("target", f"apply into {self.dirs()[0]}")]

    def ship(self, n: int, commit: str) -> str:
        from konstant.verify.holdout import HoldoutError, materialise
        d, prev, new = self.dirs()
        shutil.rmtree(new, ignore_errors=True)
        new.mkdir(parents=True)
        try:
            materialise(self.repo, commit, new)
        except HoldoutError as exc:
            shutil.rmtree(new, ignore_errors=True)
            raise TargetRefused(str(exc)) from None
        shutil.rmtree(prev, ignore_errors=True)
        if d.exists():
            d.rename(prev)
        else:
            prev.mkdir(parents=True)            # a first ship rolls back to an empty dir
        new.rename(d)
        return commit

    def rollback(self, n: int, tip: str) -> str:
        d, prev, _new = self.dirs()
        if not prev.is_dir():
            raise RollbackFailed(f"{prev} is missing: nothing to swap back")
        failed = Path(str(d) + ".failed")
        shutil.rmtree(failed, ignore_errors=True)
        d.rename(failed)
        prev.rename(d)
        shutil.rmtree(failed, ignore_errors=True)
        return self.pre


class CommandTarget(Base):
    name = "command"

    def precheck(self) -> list:
        from konstant.factory.shiprules import bad, ok
        if not self.conf["ship_cmd"] or not self.conf["rollback_cmd"]:
            return [bad("target", "the command target needs ship_cmd AND rollback_cmd: a target "
                                  "that cannot roll back may not auto-ship")]
        return [ok("target", "ship_cmd and rollback_cmd are set")]

    def _run(self, template: str, commit: str) -> subprocess.CompletedProcess:
        subst = {"{commit}": commit, "{branch}": self.branch, "{job}": str(self.job["id"])}
        argv = []
        for tok in shlex.split(template):
            for k, v in subst.items():
                tok = tok.replace(k, v)
            argv.append(tok)
        env = {**own_env(), "KONSTANT_SHIP_COMMIT": commit}
        return subprocess.run(argv, cwd=str(self.target), capture_output=True, text=True,
                              env=env, timeout=1800, stdin=subprocess.DEVNULL)

    def ship(self, n: int, commit: str) -> str:
        try:
            r = self._run(self.conf["ship_cmd"], commit)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise TargetRefused(f"ship_cmd could not run: {exc}") from None
        if r.returncode != 0:
            raise TargetRefused(f"target refused: ship_cmd exited {r.returncode}")
        return commit

    def rollback(self, n: int, tip: str) -> str:
        try:
            r = self._run(self.conf["rollback_cmd"], self.pre)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise RollbackFailed(f"rollback_cmd could not run: {exc}") from None
        if r.returncode != 0:
            raise RollbackFailed(f"rollback_cmd exited {r.returncode}")
        return self.pre


TARGETS = {t.name: t for t in (GithubTarget, BranchTarget, ApplyTarget, CommandTarget)}


def make(cfg, conf: dict, target, repo, job: dict, pre: str) -> Base:
    return TARGETS[conf["target"]](cfg, conf, target, repo, job, pre)
