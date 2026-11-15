"""`konstant doctor --live-preflight` (wave L5-L): ONE real jailed dsh phase, before a live goal,
proving from INSIDE the phase's own shell what the offline suite cannot see.

The L5-F2b live run lost every attempt because a variable konstant set for git never reached the
phase's shell (dsh drops credential-shaped names on the way into a command), while the offline
suite and CI stayed green: the stub dsh did not filter. So this check starts the configured dsh,
through the real runner path (gate/runner.PhaseRunner -> gate/harness.Harness -> the dsh adapter
-> konstant's jail -> dsh's own sandbox -> its bash tool), as the scoped tester of a throwaway
factory job, with NO model: a scripted local endpoint (harnesses/scripted.py) answers with two
`bash` tool calls and then "done". The phase works in a real job clone (factory/clone.py) of a
throwaway target under projects/, and its shell reports, one `PROBE <name> ok|fail|info` line
each: git works in the clone (rev-parse = the base, status), the clone's .git/config and the
target are read-only, its own and the viewer token are readable and every other token is not,
the sealed store (with a canary planted for this check) shows nothing, its OUT/verify-<stem>/
is writable while the other verifiers' dirs and the shared OUT files it judges are not, and the
judge command pins. konstant then checks that pin from outside with the DoD check's own rule
(gate/rules/judged.check): the same state hashed inside and outside, git keys and no tree keys.

The phase uses the workspace's dsh, profile and confinement; only the provider block of its patch
points at the scripted endpoint (dsh.patch, the same generator, in the run dir). Everything it
made (target, clone, run dir, canary) is removed afterwards; KEEP the run dir with keep=True.
"""
from __future__ import annotations

import json
import os
import secrets
import shlex
import shutil
from pathlib import Path

from konstant.harnesses.dsh import Dsh

PROBE_TIMEOUT_S = 600


def _commit(top: Path) -> str:
    from konstant.gate.rules.common import git, git_head
    ident = ["-c", "user.name=konstant preflight", "-c", "user.email=preflight@konstant.invalid",
             "-c", "commit.gpgsign=false"]
    for args in (["init", "-q", "-b", "main", "--template="], ["add", "-A"],
                 [*ident, "commit", "-q", "--no-verify", "-m", "konstant live pre-flight"]):
        r = git(top, *args)
        if r.returncode != 0:
            raise RuntimeError(f"git {args[-1]}: {(r.stderr or r.stdout).strip()[-200:]}")
    return git_head(top)


def scripts(v: dict) -> list:
    """The two commands the scripted model runs in the phase's bash tool (`v`: the paths)."""
    q = {k: shlex.quote(str(x)) for k, x in v.items()}
    for k in ("readable", "masked"):          # token file names: words of [a-z.-] only
        assert all(c.isalnum() or c in ".- " for c in v[k]), v[k]
        q[k] = v[k]
    head = ("set +e\np() { printf 'PROBE %s %s %s\\n' \"$1\" \"$2\" \"$3\"; }\n"
            f"WS={q['ws']}; CLONE={q['clone']}; OUT={q['out']}; TAG={q['tag']}\n")
    one = head + f"""
names=$(env | cut -d= -f1 | grep -E '^(GIT_|KONSTANT_|DSH_|TMPDIR$|HOME$|PATH$)' | sort | tr '\\n' ,)
p env-names info "$names"
if env | grep -q '^GIT_CONFIG_COUNT=' && ! env | grep -q '^GIT_CONFIG_KEY_0='; then
  p env-git-config fail "GIT_CONFIG_COUNT without GIT_CONFIG_KEY_0 (git refuses every call)"
else p env-git-config ok "no half GIT_CONFIG_COUNT/KEY triple"; fi
[ "$(pwd -P)" = "$CLONE" ] && p cwd ok "the job clone" || p cwd fail "cwd $(pwd -P), not $CLONE"
o=$(git rev-parse HEAD 2>&1); rc=$?
[ $rc = 0 ] && [ "$o" = {q['base']} ] && p git-rev-parse ok "HEAD = the base" \\
  || p git-rev-parse fail "rc=$rc $(printf %s "$o" | tail -c 200)"
o=$(git status --porcelain 2>&1); rc=$?
[ $rc = 0 ] && p git-status ok "$(printf %s "$o" | wc -l) changed path(s)" \\
  || p git-status fail "rc=$rc $(printf %s "$o" | tail -c 200)"
if printf '\\n' >> .git/config 2>/dev/null; then p git-config-ro fail "wrote .git/config"
else p git-config-ro ok "read-only"; fi
if : > {q['target']}/.preflight-write 2>/dev/null; then p target-ro fail "wrote the target"
else p target-ro ok "read-only"; fi
for t in {q['readable']}; do
  if cat "$WS/var/secrets/$t" >/dev/null 2>&1; then p token-own ok "$t readable"
  else p token-own fail "$t not readable"; fi
done
for t in {q['masked']}; do
  if [ -e "$WS/var/secrets/$t" ] && cat "$WS/var/secrets/$t" >/dev/null 2>&1; then
    p token-other fail "$t READABLE"; else p token-other ok "$t masked"; fi
done
n=$(ls -A {q['store']} 2>/dev/null | wc -l)
[ "$n" = 0 ] && p sealed ok "the store shows nothing" || p sealed fail "$n store entries visible"
if cat {q['store']}/{q['canary']} >/dev/null 2>&1; then p sealed-canary fail "canary readable"
else p sealed-canary ok "canary masked"; fi
if printf 'pre-flight evidence\\n' > {q['own']}/preflight.md; then p own-dir ok "writable"
else p own-dir fail "cannot write {v['own_name']}/"; fi
if printf x > {q['other']}/preflight.md 2>/dev/null; then p other-dir fail "wrote {v['other_name']}/"
else p other-dir ok "{v['other_name']}/ read-only"; fi
if printf x >> {q['shared']} 2>/dev/null; then p judged-input fail "wrote a judged OUT file"
else p judged-input ok "judged OUT files read-only"; fi
printf x > "/tmp/konstant-preflight-$TAG" 2>/dev/null && p tmp-write info "/tmp writable" \\
  || p tmp-write info "/tmp not writable"
"""
    two = head + f"""
[ -e "/tmp/konstant-preflight-$TAG" ] && p tmp-persists info "/tmp is kept between tool calls" \\
  || p tmp-persists info "every tool call gets a fresh /tmp"
o=$({v['judge']} 2>&1); rc=$?
j=$(printf '%s\\n' "$o" | grep '^# JUDGED: ' | tail -n 1)
[ $rc = 0 ] && [ -n "$j" ] && p judge ok "$j" || p judge fail "rc=$rc $(printf %s "$o" | tail -c 300)"
printf 'konstant live pre-flight\\n%s\\n# VERDICT: PASS\\n' "$j" > {q['verdict']} \\
  && p verdict ok "written" || p verdict fail "cannot write the verdict"
"""
    return [one, two]


def probes(text: str) -> list:
    out = []
    for ln in text.splitlines():
        parts = ln.split(" ", 3)
        if len(parts) >= 3 and parts[0] == "PROBE" and parts[2] in ("ok", "fail", "info"):
            out.append((parts[1], parts[2], parts[3] if len(parts) > 3 else ""))
    return out


EXPECTED = ("env-git-config", "cwd", "git-rev-parse", "git-status", "git-config-ro", "target-ro",
            "token-own", "token-other", "sealed", "sealed-canary", "own-dir", "other-dir",
            "judged-input", "judge", "verdict")


def run(cfg, keep: bool = False, log=lambda m: None) -> list:
    """(status, check, detail) rows; any FAIL row = the live path is broken."""
    from konstant import harnesses, jail
    hcfg = cfg.data["harness"]
    choice = harnesses.resolve(hcfg, "code")
    if choice.name != "dsh" or choice.template is not None:
        return [("FAIL", "live preflight", f"the code phases run on {choice.name}: the live "
                 "pre-flight starts a dsh phase only (the harness whose shell filters names)")]
    if not cfg.data["gate"]["jail"] or not jail.available():
        return [("FAIL", "live preflight", "konstant's jail is off or unavailable: no factory "
                 "phase may run")]
    ws, tag = cfg.home, secrets.token_hex(4)
    made, rows = [], []
    from konstant.harnesses.scripted import ScriptedEndpoint
    ep = ScriptedEndpoint([])
    try:
        rows = _run(cfg, ws, tag, hcfg, ep, made, log)
    except Exception as exc:                       # a broken step is a FAIL, never a traceback
        rows.append(("FAIL", "live preflight", f"{type(exc).__name__}: {exc}"))
    finally:
        ep.stop()
        for p in reversed(made):
            if keep and p.parent.name == "runs":
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except OSError:
                    pass
    return rows


def _run(cfg, ws: Path, tag: str, hcfg: dict, ep, made: list, log) -> list:
    from konstant import catalog, machinery
    from konstant.factory import clone
    from konstant.gate import harness as harness_mod
    from konstant.gate import record
    from konstant.gate.rules import judged
    from konstant.gate.rules.common import Run, cycle_name
    from konstant.gate.runner import PhaseRunner
    from konstant.harnesses import dsh
    from konstant.holdout import store
    rows = []
    projects = ws / "projects"
    projects.mkdir(exist_ok=True)
    target = projects / f".konstant-preflight-{tag}"
    made.append(target)
    target.mkdir()
    (target / "README.md").write_text("a throwaway target of `konstant doctor --live-preflight`\n")
    base = _commit(target)
    work = Path(clone.workdir_of(str(target), 1))
    made.append(work)
    clone.create(target, work, base)
    (work / "change.txt").write_text("the producer's change (uncommitted)\n")
    where = store.root(cfg)
    if not where.exists():
        where.mkdir(parents=True, mode=0o700)
        made.append(where)
    canary = f".konstant-preflight-{tag}"
    (where / canary).write_text(f"PREFLIGHT-CANARY-{secrets.token_hex(8)}\n")
    made.append(where / canary)
    cat = catalog.load(catalog.find_root(ws, cfg.data["catalog"]["path"]))
    run_dir, _stamp, _slug = record.new_run_dir(ws, "konstant live pre-flight")
    made.append(run_dir)
    out = work / ".audits" / run_dir.name / "out"
    rec = record.build(cat, "[type:code] konstant live pre-flight", "code", "pre-flight",
                       run_dir=run_dir, out=out, project=work, workspace=ws, job=None,
                       mode="runner", gate_cfg=cfg.data["gate"])
    rec["holdouts"] = 0
    record.write(run_dir, rec)
    phase = next(p for p in rec["phases"] if p.get("verdict") in rec["own_dirs"])
    (out / "evidence-architect.md").write_text("an earlier phase's evidence: judged input\n")
    pr_dirs = sorted(judged.own_dir(v) for v in rec["own_dirs"])
    own = judged.own_dir(phase["verdict"])
    other = next(d for d in pr_dirs if d != own)
    url = ep.start()
    shcfg = {**hcfg, "endpoint": {"base_url": url, "api_key_env": ""}, "model": ep.model,
             "types": {}}
    hs = harness_mod.HarnessSet(shcfg, ws, cat, cfg.data["permissions"]["allow"], jail=True,
                                factory=True, conf=cfg.confinement())
    try:
        hs.check()                     # the composed profile (dsh --dump-config, pinned, jailed)
        rows.append(("PASS", "live dsh layers", "the phase profile composes (pinned dsh, jailed)"))
    except harness_mod.HarnessError as exc:
        return rows + [("FAIL", "live dsh layers", str(exc))]
    ppath = run_dir / "preflight.patch.yml"            # the generator of .dsh/konstant.patch.yml
    ppath.write_text(dsh.patch(ws, shcfg, "konstant live pre-flight (generated)",
                               cfg.confinement(), bool(cfg.data["memory"]["enabled"])))
    hs.default.adapter = PreflightDsh(ppath)
    hs.phase_timeout = lambda agent, task_type="": PROBE_TIMEOUT_S
    readable = machinery.tokens_readable(phase.get("identity") or "worker")
    v = {"ws": ws, "clone": os.path.realpath(work), "out": out, "tag": tag, "base": base,
         "target": target, "store": where, "canary": canary,
         "readable": " ".join(readable),
         "masked": " ".join(machinery.tokens_denied(phase.get("identity") or "worker")),
         "own": out / own, "own_name": own, "other": out / other, "other_name": other,
         "shared": out / "evidence-architect.md",
         "judge": rec["judge_cmd"] + f" --for {shlex.quote(phase['verdict'])}",
         "verdict": out / cycle_name(phase["verdict"], 1)}
    ep.commands = scripts(v)
    pr = PhaseRunner(rec, cat, hs, run_dir=run_dir, max_parallel=1, log=log)
    m = pr.run_group([phase])[0]
    seen = "\n".join(ep.results.get(i, "") for i in range(len(ep.commands)))
    got = probes(seen)
    prompt_ok = any("KONSTANT-OWN-DIR:" in p for p in ep.prompts)
    rows.append(("PASS" if m["rc"] == 0 else "FAIL", "live phase",
                 f"a real jailed dsh phase ({phase['agent']}, identity {m['identity']}) exited "
                 f"{m['rc']} after {m['seconds']}s; {ep.requests} model request(s), "
                 f"{len(ep.results)}/{len(ep.commands)} tool result(s) back"
                 + ("" if m["rc"] == 0 else f"; log {m['log']}")))
    rows.append(("PASS" if prompt_ok else "FAIL", "live prompt",
                 "the phase prompt reached the model" if prompt_ok else
                 "no request carried the phase prompt (KONSTANT-OWN-DIR line)"))
    names = {n for n, _s, _d in got}
    for n, s, d in got:
        rows.append(({"ok": "PASS", "fail": "FAIL"}.get(s, "INFO"), f"in phase: {n}", d))
    for n in EXPECTED:
        if n not in names:
            rows.append(("FAIL", f"in phase: {n}", "no report from the phase's shell"))
    rows += pin_rows(Run(run_dir=run_dir, rec=rec), phase["verdict"], out)
    return rows


def pin_rows(run, verdict: str, out: Path) -> list:
    """The phase's pin checked from OUTSIDE by the DoD check's own rule (gate/rules/judged)."""
    from konstant.gate.rules import judged
    from konstant.gate.rules.verdicts import judged_line
    f = out / verdict
    sha = judged_line(f) if f.is_file() else None
    if not sha:
        return [("FAIL", "live pin", f"no `# JUDGED:` line in OUT/{verdict}")]
    mine = [x for x in judged.check(run) if getattr(x, "owner", "") == f"verifier:{verdict}"]
    try:
        keys = sorted(json.loads((out / ".tmp" / "judged" / f"{sha}.json").read_text()))
    except (OSError, ValueError):
        keys = []
    kinds = sorted({k.split("/", 1)[0] for k in keys})
    if mine:
        return [("FAIL", "live pin", f"the pin made inside the phase is stale outside: "
                 f"{mine[0].text}; keys {kinds}")]
    if "proj" in kinds or "git" not in kinds:
        return [("FAIL", "live pin", f"the phase hashed the clone without git (keys {kinds})")]
    return [("PASS", "live pin", f"the phase's pin {sha[:12]} matches outside (keys {kinds})")]


class PreflightDsh(Dsh):
    """The dsh adapter with the pre-flight's patch (the scripted endpoint) in place of the
    workspace's; everything else (env, home, jail, cleanup) is the adapter's own."""

    def __init__(self, patch_path: Path):
        self.patch_path = patch_path

    def argv(self, ph) -> list:
        return [self.binary, "--profile", "headless", "--patch", str(self.patch_path), "-"]
