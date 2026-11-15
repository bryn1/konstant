#!/usr/bin/env python3
"""A stand-in for the GitHub CLI and GitHub itself (docs/LEVEL5.md 5.6 C11, wave L5-4): no network.

`install(bindir, remote, log)` writes `<bindir>/gh`, a wrapper that runs this file with the stand-in
"GitHub" (a local bare repository) and a JSON-lines log baked in, so the ship step's own scrubbed
environment does not need to carry them. It also arms the bare repository the way a protected
GitHub branch behaves: an `update` hook logs every ref update (`ff=yes|no|new|delete`) and refuses
a non-fast-forward or a delete, and receive.denyNonFastForwards / denyDeletes are set.

Supported: `gh pr create --base B --head H --title T --body X --repo R` (prints a pull request URL)
and `gh pr merge N --merge --match-head-commit SHA --repo R` (refuses a head that moved; makes the
merge commit GitHub's merge button makes: the head's tree, parents base + head). `--refuse
rollback-merge` (wrapper option) refuses merges of `konstant/rollback-*` heads, `--refuse merge`
every merge. Every call is one log line.

`--intervene FILE` (wave L5-F2b, REVIEW L5-R2 K-14) models what real GitHub does when someone
else's pull request lands between konstant's precheck and its merge: on the next merge of a
`konstant/ship-*` head, FILE (JSON {"path", "text"}) is first committed onto the base branch by
"someone else" (one shot: FILE is removed), and a merge whose base moved is then made the way
GitHub makes it - a three-way merge of the trees (read-tree -m), refused only on a conflict -
instead of the default "not mergeable".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

IDENT = {"GIT_AUTHOR_NAME": "GitHub", "GIT_AUTHOR_EMAIL": "noreply@github.example",
         "GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": "noreply@github.example",
         "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
HOOK = """#!/bin/sh
ref="$1"; old="$2"; new="$3"
zero=0000000000000000000000000000000000000000
if [ "$new" = "$zero" ]; then kind=delete
elif [ "$old" = "$zero" ]; then kind=new
elif git merge-base --is-ancestor "$old" "$new"; then kind=yes
else kind=no; fi
echo "update $ref $old $new ff=$kind" >> "{log}"
[ "$kind" = no ] && { echo "non-fast-forward refused" >&2; exit 1; }
[ "$kind" = delete ] && { echo "delete refused" >&2; exit 1; }
exit 0
"""


def install(bindir: Path, remote: Path, log: Path, refuse: str = "",
            intervene: Path | None = None) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    gh = bindir / "gh"
    iv = f"--intervene {intervene} " if intervene else ""
    gh.write_text(f"#!/bin/sh\nexec {sys.executable} {Path(__file__).resolve()} --remote "
                  f"{remote} --log {log} {iv}--refuse '{refuse}' \"$@\"\n")
    gh.chmod(0o755)
    hooks = remote / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "update").write_text(HOOK.replace("{log}", str(log) + ".push"))
    (hooks / "update").chmod(0o755)
    for k in ("receive.denyNonFastForwards", "receive.denyDeletes"):
        subprocess.run(["git", "-C", str(remote), "config", k, "true"], check=True, env={
            **os.environ, **IDENT})
    return gh


def git(remote, *args) -> str:
    r = subprocess.run(["git", "-C", str(remote), *args], capture_output=True, text=True,
                       env={**os.environ, **IDENT})
    if r.returncode != 0:
        raise SystemExit(f"fake gh: git {args[0]} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def opt(args: list, name: str) -> str:
    return args[args.index(name) + 1] if name in args else ""


def _index_env(path: str) -> dict:
    return {**os.environ, **IDENT, "GIT_INDEX_FILE": path}


def intervene(remote, base: str, spec: Path) -> str:
    """Someone else's change lands on `base` first (one shot)."""
    want = json.loads(spec.read_text())
    spec.unlink()
    tip = git(remote, "rev-parse", "--verify", f"refs/heads/{base}")
    idx = str(spec) + ".index"
    env = _index_env(idx)
    run = lambda *a, **kw: subprocess.run(["git", "-C", str(remote), *a], env=env,  # noqa: E731
                                          capture_output=True, text=True, check=True, **kw)
    run("read-tree", tip)
    blob = run("hash-object", "-w", "--stdin", input=want["text"]).stdout.strip()
    run("update-index", "--add", "--cacheinfo", f"100644,{blob},{want['path']}")
    tree = run("write-tree").stdout.strip()
    os.unlink(idx)
    other = git(remote, "commit-tree", tree, "-p", tip, "-m", "someone else's pull request")
    git(remote, "update-ref", f"refs/heads/{base}", other, tip)
    return other


def merge3(remote, base_tip: str, head: str) -> str:
    """GitHub's merge of a head whose base moved: a three-way tree merge, "" on a conflict."""
    mb = git(remote, "merge-base", base_tip, head)
    idx = os.path.join(str(remote), "fake-gh-merge.index")
    env = _index_env(idx)
    try:
        r = subprocess.run(["git", "-C", str(remote), "read-tree", "-m", "-i", "--aggressive",
                            mb, base_tip, head], env=env, capture_output=True, text=True)
        w = subprocess.run(["git", "-C", str(remote), "write-tree"], env=env,
                           capture_output=True, text=True)
        return w.stdout.strip() if r.returncode == 0 and w.returncode == 0 else ""
    finally:
        if os.path.exists(idx):
            os.unlink(idx)


def main(argv: list) -> int:
    remote, log, refuse = opt(argv, "--remote"), opt(argv, "--log"), opt(argv, "--refuse")
    spec = Path(opt(argv, "--intervene")) if "--intervene" in argv[:argv.index("--refuse")] \
        else None
    args = argv[argv.index("--refuse") + 2:]
    state_path = Path(log + ".state")
    state = json.loads(state_path.read_text()) if state_path.is_file() else {"prs": []}

    def record(**row):
        with open(log, "a") as fh:
            fh.write(json.dumps({"argv": args, **row}) + "\n")

    if args[:2] == ["pr", "create"]:
        head, base = opt(args, "--head"), opt(args, "--base")
        sha = git(remote, "rev-parse", "--verify", f"refs/heads/{head}")
        n = len(state["prs"]) + 1
        state["prs"].append({"number": n, "head": head, "base": base, "sha": sha,
                             "title": opt(args, "--title"), "state": "open"})
        state_path.write_text(json.dumps(state))
        record(call="pr create", pr=n, head=head, base=base, sha=sha, repo=opt(args, "--repo"))
        print(f"https://github.example/{opt(args, '--repo')}/pull/{n}")
        return 0
    if args[:2] == ["pr", "merge"]:
        n = int(args[2])
        pr = state["prs"][n - 1]
        match = opt(args, "--match-head-commit")
        head_now = git(remote, "rev-parse", "--verify", f"refs/heads/{pr['head']}")
        refused = refuse == "merge" or (refuse == "rollback-merge"
                                        and pr["head"].startswith("konstant/rollback-"))
        if "--merge" not in args or match != head_now or refused:
            record(call="pr merge", pr=n, refused=True, sha=match)
            print("fake gh: merge refused" + (" (head moved)" if match != head_now else ""),
                  file=sys.stderr)
            return 1
        if spec is not None and spec.is_file() and pr["head"].startswith("konstant/ship-"):
            record(call="intervene", commit=intervene(remote, pr["base"], spec))
        base_tip = git(remote, "rev-parse", "--verify", f"refs/heads/{pr['base']}")
        ff = subprocess.run(["git", "-C", remote, "merge-base", "--is-ancestor", base_tip,
                             head_now], env={**os.environ, **IDENT}).returncode == 0
        tree = f"{head_now}^{{tree}}" if ff else (merge3(remote, base_tip, head_now)
                                                  if spec is not None else "")
        if not tree:
            record(call="pr merge", pr=n, refused=True, sha=match, reason="not mergeable")
            print("fake gh: not mergeable", file=sys.stderr)
            return 1
        merge = git(remote, "commit-tree", tree, "-p", base_tip, "-p",
                    head_now, "-m", f"Merge pull request #{n} from {pr['head']}")
        git(remote, "update-ref", f"refs/heads/{pr['base']}", merge, base_tip)
        pr["state"] = "merged"
        state_path.write_text(json.dumps(state))
        record(call="pr merge", pr=n, sha=match, merge=merge, head=pr["head"],
               revert=pr["head"].startswith("konstant/rollback-"))
        return 0
    record(call="unsupported")
    print(f"fake gh: unsupported command {' '.join(args)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
