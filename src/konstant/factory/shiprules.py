"""The ship guard's rules (docs/LEVEL5.md 5.2, 5.4), as pure checks both sides run: the factory
before it moves anything (factory/ship.py) and the board again on POST /api/jobs/{ref}/ships
(board/api/ships.py). Each check returns (rule, ok, reason); a ship goes ahead only when every rule
is ok, and the decision rules (5.4) may be ok because the owner approved that exact commit.

- `verified_rules`: the job is verified, its latest verification is PASS and carries the holdout
  result of the sealed set: at least min_per_job rows, every one passed, the commitment digest of
  the sealed set, no LEAK, and every row ran on the SAME commit the evidence names and the ship
  is about to ship. A level-4 job (no holdouts) fails here: never ship without a matched holdout.
- `decision_paths`: a diff that touches a project instruction surface, an import hook, a
  `conftest.py` outside a test dir or a CI workflow is an owner decision, whatever the type.
- `secret_findings`: the release scanner's patterns (release/patterns.toml plus a denylist when one
  is configured) over the ADDED lines of every changed text file and over every changed path: a
  finding is an owner decision and nothing is pushed. Findings name the path and the pattern,
  never the matched text.
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path, PurePosixPath

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
INSTRUCTION_DIRS = (".claude", ".agents", ".dsh", ".gemini")
IMPORT_HOOKS = ("sitecustomize.py", "usercustomize.py")
TEST_DIRS = ("tests", "test", "testing")
CI_PREFIXES = (".github/workflows/", ".github/actions/")


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


def decision_paths(changed: list) -> list:
    """One reason per changed path that only the owner may ship (5.4)."""
    out = []
    for path in changed:
        p = PurePosixPath(path)
        parts = p.parts
        if p.name in INSTRUCTION_FILES or any(x in INSTRUCTION_DIRS for x in parts[:-1]):
            out.append(f"instruction surface changed ({path})")
        elif p.name in IMPORT_HOOKS or p.suffix == ".pth":
            out.append(f"import hook changed ({path})")
        elif p.name == "conftest.py" and not any(x in TEST_DIRS for x in parts[:-1]):
            out.append(f"conftest.py outside a test dir changed ({path})")
        elif any(str(p).startswith(c) for c in CI_PREFIXES):
            out.append(f"CI workflow changed ({path})")
    return out


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
    """Where and how a job ships: the goal's [ship] (defaults applied when it was filed), else the
    workspace's [factory] defaults; konstant.toml [ship] fills what the goal does not name. The push
    URL (`remote`), the gh binary and the denylist are the operator's alone: a goal names none."""
    from konstant.factory.goal import effective_defaults
    d = effective_defaults(cfg.data["factory"]["defaults"])
    s = cfg.data["ship"]
    g = (spec or {}).get("ship") or {}
    out = {"target": g.get("target") or d["ship_target"],
           "branch": g.get("branch") or d["ship_branch"],
           "post_probes": list(s["post_probes"]) + [p for p in g.get("post_probes") or []
                                                    if p not in s["post_probes"]],
           "remote": s["remote"], "gh": s["gh"], "regression_only": s["regression_only"]}
    for k in ("github_repo", "apply_dir", "ship_cmd", "rollback_cmd"):
        out[k] = g.get(k) or s[k]
    if out["target"] == "github" and not out["remote"] and out["github_repo"]:
        out["remote"] = f"https://github.com/{out['github_repo']}.git"
    return out
