"""The ship guard's rules (docs/LEVEL5.md 5.2, 5.4), as pure checks both sides run: the factory
before it moves anything (factory/ship.py) and the board again on POST /api/jobs/{ref}/ships
(board/api/ships.py). Each check returns (rule, ok, reason); a ship goes ahead only when every rule
is ok, and the decision rules (5.4) may be ok because the owner approved that exact commit.

- `verified_rules`: the job is verified, its latest verification is PASS and carries the holdout
  result of the sealed set: at least min_per_job rows, every one passed, the commitment digest of
  the sealed set, no LEAK, and every row ran on the SAME commit the evidence names and the ship
  is about to ship. A level-4 job (no holdouts) fails here: never ship without a matched holdout.
- `decision_paths` / `decision_reasons`: a diff that touches any path of DECISION_LIST (agent
  instruction surfaces, import hooks, code-loading config, `conftest.py` anywhere, editor tasks,
  submodules, all of `.github/`, the scripts of `package.json`, `[tool.pytest]` of
  `pyproject.toml`) is an owner decision, whatever the type. DECISION_LIST is the ONE list: the
  docs (docs/LEVEL5.md 5.4) name every entry and tests/review/test_level5_r2_ship.py checks they
  agree (REVIEW L5-R2 K-15).
- `history_rule`: the verified commit must descend from the target's tip `pre` (a fast-forward);
  an orphan or unrelated history is an owner decision (REVIEW L5-R2 K-04). What is pushed is never
  that history anyway: the ship moves the target to konstant's own squash commit (shiprepo.squash).
- `secret_findings`: the release scanner's patterns (release/patterns.toml plus a denylist when one
  is configured) over the ADDED lines of every changed text file and over every changed path: a
  finding is an owner decision and nothing is pushed. Findings name the path and the pattern,
  never the matched text.
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path, PurePosixPath

try:  # Python >= 3.11
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as _toml

# DECISION_LIST (docs/LEVEL5.md 5.4): (kind, name, what). Names compare case-insensitively.
#   name    a file of that name in any directory
#   dir     any path below a directory of that name, at any depth
#   suffix  a file name ending so
#   content the file's code-loading part changed (decision_content reads old and new)
DECISION_LIST = (
    ("name", "AGENTS.md", "instruction surface"), ("name", "CLAUDE.md", "instruction surface"),
    ("name", "CLAUDE.local.md", "instruction surface"), ("name", "GEMINI.md", "instruction surface"),
    ("dir", ".claude", "instruction surface"), ("dir", ".agents", "instruction surface"),
    ("dir", ".dsh", "instruction surface"), ("dir", ".gemini", "instruction surface"),
    ("dir", ".codex", "instruction surface"), ("dir", ".cursor", "instruction surface"),
    ("dir", ".github", "GitHub configuration (workflows, actions, bots, instructions)"),
    ("name", "sitecustomize.py", "import hook"), ("name", "usercustomize.py", "import hook"),
    ("suffix", ".pth", "import hook"),
    ("name", "conftest.py", "test-runner hook"), ("name", "pytest.ini", "test-runner config"),
    ("name", "setup.cfg", "test-runner config"), ("name", "tox.ini", "test-runner config"),
    ("name", "noxfile.py", "test-runner config"),
    ("name", ".envrc", "shell environment hook"),
    ("name", ".pre-commit-config.yaml", "git hook config"),
    ("name", ".gitmodules", "submodule"), ("name", ".gitattributes", "git filter config"),
    ("name", "Makefile", "build commands"), ("name", "GNUmakefile", "build commands"),
    ("name", "justfile", "build commands"),
    ("dir", ".vscode", "editor tasks"), ("dir", ".idea", "editor tasks"),
    ("dir", ".devcontainer", "container config"),
    ("content", "package.json", "package scripts or hooks"),
    ("content", "pyproject.toml", "[tool.pytest] of pyproject.toml"),
)
# package.json keys that make a tool run code (npm scripts and the git-hook managers)
PACKAGE_KEYS = ("scripts", "husky", "simple-git-hooks", "lint-staged", "pre-commit",
                "gitHooks", "config")


def ok(rule: str, reason: str = "ok") -> tuple:
    return (rule, True, reason)


def bad(rule: str, reason: str) -> tuple:
    return (rule, False, reason)


def _loads(raw):
    if raw is None or isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def verified_rules(job: dict, verification: dict | None, sealed: list, min_per_job: int,
                   commit: str) -> list:
    """Rules 1-3 of 5.2 over board records: `job` (status, evidence), `verification` (its latest
    row: verdict, holdout_json), `sealed` (the job's sealed holdout rows: hid, sha256)."""
    from konstant.verify.holdout import digest
    rules = []
    if job.get("status") != "verified" or not verification or \
            verification.get("verdict") != "PASS":
        rules.append(bad("verified", f"job {job.get('id')} is {job.get('status')}: only a "
                                     "verified job whose latest verification is PASS ships"))
        return rules
    rules.append(ok("verified"))
    h = _loads(verification.get("holdout_json") if "holdout_json" in verification
               else verification.get("holdouts"))
    ev = job.get("evidence") or _loads(job.get("evidence_json")) or {}
    rows = (h or {}).get("rows") or []
    if not h or not rows or not sealed:
        rules.append(bad("holdouts", f"refused: no holdout PASS for commit {commit[:12]} (a job "
                                     "without sealed holdouts is never shipped by the factory)"))
        return rules
    good = (not h.get("leak") and len(rows) >= max(1, min_per_job)
            and len(rows) == len(sealed) and all(r.get("passed") is True for r in rows)
            and {r.get("hid") for r in rows} == {r["hid"] for r in sealed}
            and h.get("digest") == digest(sealed))
    if not good:
        rules.append(bad("holdouts", f"refused: no holdout PASS for commit {commit[:12]}: the "
                                     "latest verification does not carry every sealed holdout "
                                     "passed with the set's commitment digest and no LEAK"))
        return rules
    rules.append(ok("holdouts", f"{len(rows)} holdout(s) passed, digest matches, no LEAK"))
    ran = {r.get("commit") for r in rows} | {h.get("commit")}
    evc = (ev.get("commit") or "").strip()
    if len(ran) != 1:
        rules.append(bad("commit", "refused: the holdouts ran on more than one commit"))
    elif evc != next(iter(ran)):
        rules.append(bad("commit", f"refused: holdouts ran on {next(iter(ran))}, the evidence "
                                   f"names {evc or 'no commit'}"))
    elif commit != evc:
        rules.append(bad("commit", f"refused: holdouts ran on {evc}, the ship would ship "
                                   f"{commit}"))
    else:
        rules.append(ok("commit", f"holdouts, evidence and ship all name {commit[:12]}"))
    return rules


def regression_only(sealed: list) -> bool:
    return bool(sealed) and all(r.get("kind") == "regression" for r in sealed)


def _match(kind: str, name: str, p: PurePosixPath) -> bool:
    low = name.lower()
    if kind in ("name", "content"):
        return p.name.lower() == low
    if kind == "dir":
        return any(x.lower() == low for x in p.parts[:-1])
    return p.name.lower().endswith(low)


def decision_paths(changed: list) -> list:
    """One reason per changed path that only the owner may ship (5.4), by its path alone (the
    `content` rows need the file: decision_reasons)."""
    out = []
    for path in changed:
        p = PurePosixPath(path)
        for kind, name, what in DECISION_LIST:
            if kind != "content" and _match(kind, name, p):
                out.append(f"{what} changed ({path})")
                break
    return out


def _pytest_tables(data: bytes | None) -> str:
    if not data:
        return ""
    try:
        raw = _toml.loads(data.decode("utf-8", "replace"))
    except (ValueError, UnicodeError):
        return "<unparsable>"
    return json.dumps(((raw.get("tool") or {}).get("pytest")), sort_keys=True)


def _package_keys(data: bytes | None) -> str:
    if not data:
        return ""
    try:
        raw = json.loads(data.decode("utf-8", "replace"))
    except ValueError:
        return "<unparsable>"
    if not isinstance(raw, dict):
        return "<not an object>"
    return json.dumps({k: raw.get(k) for k in PACKAGE_KEYS}, sort_keys=True)


def decision_content(path: str, old: bytes | None, new: bytes | None) -> str | None:
    """The reason a `content` row of DECISION_LIST stops this change (None: it does not)."""
    p = PurePosixPath(path)
    for kind, name, what in DECISION_LIST:
        if kind == "content" and _match(kind, name, p):
            f = _package_keys if name == "package.json" else _pytest_tables
            if f(old) != f(new):
                return f"{what} changed ({path})"
    return None


def decision_reasons(repo, pre: str, commit: str) -> list:
    """Every DECISION_LIST reason of the change pre..commit in ship repository `repo` (both
    sides of the guard call this)."""
    from konstant.factory import shiprepo
    rows = shiprepo.changes(repo, pre, commit)
    reasons = decision_paths([r[1] for r in rows])
    zero = {"0" * 40, "0" * 64}
    content = [r for r in rows if any(k == "content" and _match(k, n, PurePosixPath(r[1]))
                                      for k, n, _w in DECISION_LIST)]
    oids = [o for _s, _p, oo, no, _m in content for o in (oo, no) if o not in zero]
    blobs = shiprepo.read_batch(repo, list(dict.fromkeys(oids)))
    for _st, path, oo, no, _m in content:
        why = decision_content(path, blobs[oo][1] if oo not in zero else None,
                               blobs[no][1] if no not in zero else None)
        if why:
            reasons.append(why)
    return reasons


def history_rule(repo, pre: str, commit: str) -> list:
    """[reason] when `commit` does not descend from `pre` (K-04): an owner decision."""
    from konstant.factory import shiprepo
    if shiprepo.is_ancestor(repo, pre, commit):
        return []
    return [f"the verified commit {commit[:12]} does not descend from the target's tip "
            f"{pre[:12]} (unrelated or rewritten history)"]


def patterns(cfg) -> list:
    """The release scanner's patterns + the configured denylist ([ship] denylist, else the
    maintainer's release/denylist.local.txt when present). ScanError when unreadable."""
    from konstant.release import scan
    src = cfg.home / "release" / "patterns.toml"
    pats = scan.load_patterns(src if src.is_file() else scan.default_patterns_path())
    deny = cfg.data["ship"]["denylist"]
    path = cfg.resolve(deny) if deny else cfg.home / "release" / "denylist.local.txt"
    if deny or path.is_file():
        pats += scan.load_denylist(Path(path))
    return pats


def added_text(old: bytes | None, new: bytes) -> str | None:
    """The lines of `new` that `old` does not have (None for a binary file)."""
    if b"\0" in new[:8192]:
        return None
    nl = new.decode("utf-8", "replace").splitlines()
    if not old:
        return "\n".join(nl)
    ol = old.decode("utf-8", "replace").splitlines()
    return "\n".join(ln[2:] for ln in difflib.ndiff(ol, nl) if ln.startswith("+ "))


def secret_findings(repo, pre: str, commit: str, pats: list) -> list:
    """`path: pattern` per finding in the diff pre..commit (paths and added lines)."""
    from konstant.factory import shiprepo
    from konstant.release import scan
    rows = shiprepo.changes(repo, pre, commit)
    zero = {"0" * 40, "0" * 64}
    oids = [o for _s, _p, oo, no, _m in rows for o in (oo, no) if o not in zero]
    blobs = shiprepo.read_batch(repo, list(dict.fromkeys(oids)))
    found = []
    for st, path, oo, no, _m in rows:
        names = {f.pattern for f in scan.scan_text(path, path, pats)}
        if st != "D" and no not in zero:
            text = added_text(blobs.get(oo, ("", b""))[1] if oo not in zero else None,
                              blobs[no][1])
            if text:
                names |= {f.pattern for f in scan.scan_text(path, text, pats)}
        found += [f"{path} ({n})" for n in sorted(names)]
    return found


def conf(cfg, spec: dict | None) -> dict:
    """Where and how a job ships: konstant.toml [ship] and [factory] defaults ONLY. A goal adds
    post_probes (more checks, which can only stop a ship) and nothing else: target, branch,
    commands, apply dir, repository, remote and gh are the operator's (REVIEW L5-R2 K-02). A goal
    filed before that rule carries [ship] keys in its spec: they are ignored here, on both sides
    of the guard."""
    from konstant.factory.goal import effective_defaults
    d = effective_defaults(cfg.data["factory"]["defaults"])
    s = cfg.data["ship"]
    g = (spec or {}).get("ship") or {}
    out = {"target": d["ship_target"], "branch": d["ship_branch"],
           "post_probes": list(s["post_probes"]) + [p for p in g.get("post_probes") or []
                                                    if p not in s["post_probes"]],
           "remote": s["remote"], "gh": s["gh"], "regression_only": s["regression_only"]}
    for k in ("github_repo", "apply_dir", "ship_cmd", "rollback_cmd"):
        out[k] = s[k]
    if out["target"] == "github" and not out["remote"] and out["github_repo"]:
        out["remote"] = f"https://github.com/{out['github_repo']}.git"
    return out
