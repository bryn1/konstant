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


def install(bindir: Path, remote: Path, log: Path, refuse: str = "") -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(f"#!/bin/sh\nexec {sys.executable} {Path(__file__).resolve()} --remote "
                  f"{remote} --log {log} --refuse '{refuse}' \"$@\"\n")
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


def main(argv: list) -> int:
    remote, log, refuse = opt(argv, "--remote"), opt(argv, "--log"), opt(argv, "--refuse")
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
        base_tip = git(remote, "rev-parse", "--verify", f"refs/heads/{pr['base']}")
        ff = subprocess.run(["git", "-C", remote, "merge-base", "--is-ancestor", base_tip,
                             head_now], env={**os.environ, **IDENT}).returncode == 0
        if not ff:
            record(call="pr merge", pr=n, refused=True, sha=match, reason="not mergeable")
            print("fake gh: not mergeable", file=sys.stderr)
            return 1
        merge = git(remote, "commit-tree", f"{head_now}^{{tree}}", "-p", base_tip, "-p",
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
