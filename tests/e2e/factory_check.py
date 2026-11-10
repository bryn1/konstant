#!/usr/bin/env python3
"""Artifact checks for tests/e2e/factory.sh (docs/LEVEL5.md 7, wave L5-6).

Each leg's verdict is read from ARTIFACTS, never from the loop's own summary: the board's JSON
(`goal show`, `job show`, `ship list`, `factory escalations`, read as the viewer), the git refs of
the target and of the github stand-in's bare repository, the stand-in's call log and its update-hook
log, the events file, the chat inbox of the orchestrator session, the session turns' logs (the stub
dsh's STUB_DSH_LOG) and the phase logs of the runs.

  factory_check.py spec ID PROJECT [--limits L] [--ship S] [--holdout H]  the goal the scripted
        orchestrator proposes: examples/greeter/goal.toml with its id/project and extra lines
  factory_check.py turn LOG             print what one session turn did (plugin + model actions)
  factory_check.py LEG [key=value ...]  one leg's checks: p0 p1 p2 p3 p3-jail p4 p5a p5b p6 p6-refused
        owner-wait owner-done chat-all; prints `ok: ...` per check, exit 1 at the first failure

Environment: KONSTANT_E2E_WS (the installed workspace), KONSTANT_E2E_SESSION (the chat session).
Only the standard library; run with the workspace's own Python (`-I`).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

WS = Path(os.environ.get("KONSTANT_E2E_WS", "."))
SESSION = os.environ.get("KONSTANT_E2E_SESSION", "")
K = str(WS / "bin" / "konstant")
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class Fail(Exception):
    pass


def ok(cond, what: str, detail="") -> None:
    if not cond:
        raise Fail(f"{what}" + (f": {detail}" if detail != "" else ""))
    print(f"  ok: {what}")


def kj(*args, role: str = "viewer"):
    r = subprocess.run([K, "--as", role, *map(str, args), "--json"], capture_output=True, text=True,
                       cwd=str(WS), stdin=subprocess.DEVNULL, timeout=120)
    if r.returncode != 0:
        raise Fail(f"konstant {' '.join(args)} failed ({r.returncode}): {r.stderr.strip()[-400:]}")
    return json.loads(r.stdout)


def git(repo, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       env=GIT_ENV)
    return r.stdout.strip() if r.returncode == 0 else ""


def git_rc(repo, *args) -> int:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          env=GIT_ENV).returncode


def lines_of(p: Path) -> list:
    return p.read_text().splitlines() if p.is_file() else []


def events(goal: str | None = None) -> list:
    rows = [json.loads(x) for x in lines_of(WS / "var" / "factory" / "events.jsonl")]
    return [e for e in rows if goal is None or e.get("goal") == goal]


def inbox(goal: str | None = None) -> list:
    rows = [json.loads(x) for x in
            lines_of(WS / "var" / "factory" / "chat" / "inbox" / f"{SESSION}.jsonl")]
    return [e for e in rows if goal is None or e.get("goal") == goal]


def goal_jobs(goal: str) -> list:
    g = kj("goal", "show", goal)
    rows = kj("job", "list", "--project", g["project"])
    return [j for j in rows if j.get("goal") == goal]


def ships_of(jobs) -> list:
    ids = {j["id"] for j in jobs}
    return [s for s in kj("ship", "list") if s["job_id"] in ids]


def run_dirs(job_ids) -> list:
    out = []
    for d in sorted((WS / "var" / "runs").iterdir()) if (WS / "var" / "runs").is_dir() else []:
        try:
            rec = json.loads((d / "record.json").read_text())
        except (OSError, ValueError):
            continue
        if rec.get("job") in job_ids:
            out.append(d)
    return out


def phase_log(dirs) -> str:
    return "".join(p.read_text(errors="replace") for d in dirs
                   for p in sorted((d / "phases").glob("*.log")))


def target(goal: str) -> Path:
    return WS / "projects" / kj("goal", "show", goal)["project"]


def no_notify_log() -> None:
    p = WS / "var" / "factory" / "notify.log"
    ok(not p.exists(), "no notify.log ([notify] kind = chat; nothing halted)",
       p.read_text()[:300] if p.exists() else "")


def factory_stopped() -> None:
    st = kj("factory", "status")
    ok(st.get("state") == "stopped", "factory status: stopped (the loop exited cleanly)",
       st.get("state"))
    ok(not (WS / "var" / "factory" / "factory.pid").exists() or st.get("state") == "stopped",
       "no live factory pid")


def escalations_told(goal: str, kind: str, n: int = 1) -> list:
    rows = [e for e in inbox(goal) if e["event"] == kind]
    ok(len(rows) == n, f"chat inbox: {n} {kind} for goal {goal}",
       [e["reason"] for e in inbox(goal)])
    other = [e["event"] for e in inbox(goal) if e["event"] != kind]
    ok(other == [], f"chat inbox: nothing else for goal {goal}", other)
    return rows


# --- the goal the scripted orchestrator proposes -----------------------------------------------

def spec(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="factory_check.py spec")
    ap.add_argument("id")
    ap.add_argument("project")
    ap.add_argument("--limits", action="append", default=[])
    ap.add_argument("--ship", action="append", default=[])
    ap.add_argument("--holdout", action="append", default=[])
    a = ap.parse_args(argv)
    text = (WS / "examples" / "greeter" / "goal.toml").read_text()
    text = re.sub(r'(?m)^id = "greeter"$', f'id = "{a.id}"', text, count=1)
    text = re.sub(r'(?m)^project = "greeter"$', f'project = "{a.project}"', text, count=1)
    if a.id != "greeter":
        text = text.replace("make greeter greet", f"make {a.project} greet", 1)
    for table, extra in (("limits", a.limits), ("ship", a.ship)):
        if extra:
            text = text.replace(f"[{table}]\n", f"[{table}]\n" + "".join(x + "\n" for x in extra), 1)
    if a.holdout:
        text += "\n[holdout]\n" + "".join(x + "\n" for x in a.holdout)
    sys.stdout.write(text)
    return 0


def turn(argv) -> int:
    """One session turn: the plugin's `chat turn` reply and the model's actions."""
    for rec in map(json.loads, lines_of(Path(argv[0]))):
        if "act" not in rec:
            continue
        cmd = rec["act"][len("run:"):]
        short = re.sub(r"/\S*/bin/konstant", "bin/konstant", cmd)
        short = re.sub(r"< \S*/", "< ", short)
        print(f"  [session] {short}  (rc {rec.get('rc')})")
        out = (rec.get("out") or "") + (rec.get("err") or "")
        try:
            j = json.loads(rec.get("out") or "")
        except ValueError:
            j = None
        if isinstance(j, dict) and "lines" in j:
            print(f"    plugin: intake={j['intake']} confirmed={j['confirmed']} "
                  f"withdrawn={j['withdrawn']}")
            for ln in j["lines"]:
                print(f"    | {ln}")
            if j["block"]:
                print(f"    | (INTAKE block, {len(j['block'])} chars)")
        else:
            for ln in out.strip().splitlines()[:6]:
                print(f"    | {ln}")
    return 0


def turn_json(log: str, n: int = 0) -> dict:
    """The plugin's reply in a turn log (the n-th `chat turn` action)."""
    rows = [r for r in map(json.loads, lines_of(Path(log))) if " chat turn " in r.get("act", "")]
    if len(rows) <= n:
        raise Fail(f"turn log {log} has no chat turn #{n}")
    ok(rows[n].get("rc") == 0, "the plugin's chat turn ran (rc 0)", rows[n].get("err", "")[-300:])
    return json.loads(rows[n]["out"])


def model_acts(log: str) -> list:
    return [r for r in map(json.loads, lines_of(Path(log)))
            if "act" in r and " chat turn " not in r["act"]]


# --- legs --------------------------------------------------------------------------------------

def p0(kw) -> None:
    """Chat intake: request -> INTAKE block -> proposal -> the owner's yes -> filed from chat."""
    goal, req, yes = kw["goal"], kw["request_log"], kw["yes_log"]
    t = turn_json(req)
    ok(t["intake"] is True and "goal add - --from-chat --session " + SESSION in t["block"],
       "the owner's request got the INTAKE block (no level-4 gate, no work in the chat)")
    acts = model_acts(req)
    ok(len(acts) == 1 and acts[0]["rc"] == 0 and acts[0]["out"].startswith(f"PROPOSED: goal {goal}"),
       "the orchestrator proposed the goal in the same turn", [a.get("out") for a in acts])
    if kw.get("before_yes"):
        ok(json.loads(Path(kw["before_yes"]).read_text())["status"] == "proposed",
           "before the yes the goal was only proposed")
    t = turn_json(yes)
    ok(t["confirmed"] == goal and t["lines"][0].startswith(f"konstant: goal {goal} FILED from this chat"),
       "the owner's yes filed it", t["lines"])
    g = kj("goal", "show", goal)
    ok(g["status"] == "active" and g["source"] == "chat" and g["session"] == SESSION,
       f"goal {goal}: active, source chat, session {SESSION}", (g["status"], g["source"]))
    if kw.get("only_max_attempts"):
        limits = {k: v for k, v in g["limits"].items() if v not in (0, "0", None)}
        ok(limits == {"max_attempts": 3}, "max_attempts = 3 is its only limit", limits)
    copy = WS / "var" / "factory" / "goals" / f"{goal}.toml"
    ok(copy.read_text() == Path(kw["spec"]).read_text(),
       "the board's goal copy is the proposed spec, byte for byte")


def p1(kw) -> None:
    """Honest: every job verified + shipped, one fast-forward per job, nothing escalated."""
    goal = kw["goal"]
    jobs = goal_jobs(goal)
    ok(len(jobs) >= 2 and all(j["status"] == "verified" for j in jobs),
       f"every backlog job of {goal} verified", [(j["display_id"], j["status"]) for j in jobs])
    ships = ships_of(jobs)
    ok(len(ships) == len(jobs) and all(s["state"] == "shipped" for s in ships),
       "ship list: every job shipped", [(s["job_id"], s["state"]) for s in ships])
    t = target(goal)
    base = kw["base"]
    chain = git(t, "rev-list", "--first-parent", "--reverse", f"{base}..main").split()
    ok(len(chain) == len(jobs), f"target main moved by exactly one step per job ({len(jobs)})",
       chain)
    ok(git_rc(t, "merge-base", "--is-ancestor", base, "main") == 0,
       "every move was a fast-forward of the base")
    commits = [kj("job", "show", j["id"])["evidence"]["commit"] for j in jobs]
    for c in commits:
        ok(git_rc(t, "merge-base", "--is-ancestor", c, "main") == 0,
           f"verified commit {c[:12]} is on main")
    ok(git(t, "rev-parse", "main^{tree}") == git(t, "rev-parse", f"{commits[-1]}^{{tree}}"),
       "main's tree is the last verified commit's tree")
    ok(inbox(goal) == [], f"chat inbox: no escalation for {goal}", inbox(goal))
    evs = [e["event"] for e in events(goal)]
    ok(evs.count("SHIPPED") == len(jobs) and "GOAL_DONE" in evs, "events: SHIPPED per job and "
       "GOAL_DONE", evs)
    ok(kj("goal", "show", goal)["status"] == "done", f"goal {goal} done")
    if kw.get("next_turn"):
        t = turn_json(kw["next_turn"])
        out = [ln for ln in t["lines"] if ln.startswith("konstant outcomes")]
        ok(out and f"GOAL_DONE {goal}" in out[0], "the session's next turn reports GOAL_DONE",
           t["lines"])
    no_notify_log()
    factory_stopped()


def gh_calls(log: str) -> list:
    return [json.loads(x) for x in lines_of(Path(log))]


def no_force(log: str) -> None:
    pushes = lines_of(Path(log + ".push"))
    ok(pushes and all(" ff=yes" in p or " ff=new" in p for p in pushes),
       f"the stand-in saw {len(pushes)} ref update(s), every one a fast-forward or a new branch "
       "(no force-push, no delete)", pushes)


def p6(kw) -> None:
    """github target: the ships of `goal` arrived through recorded pull requests."""
    goal, log, remote = kw["goal"], kw["log"], kw["remote"]
    jobs = goal_jobs(goal)
    ships = ships_of(jobs)
    calls = gh_calls(log)
    creates = [c for c in calls if c["call"] == "pr create"]
    merges = [c for c in calls if c["call"] == "pr merge" and not c.get("refused")]
    ok(len(creates) == len(merges) == len(ships) + int(kw.get("rollbacks", 0)),
       "one pull request created and merged per ship (and per rollback)",
       [c["call"] for c in calls])
    for c, m in zip(creates, merges):
        argv = m["argv"]
        ok("--match-head-commit" in argv and argv[argv.index("--match-head-commit") + 1] == c["sha"],
           f"PR #{c['pr']} ({c['head']}) merged with --match-head-commit {c['sha'][:12]}")
        ok(c["repo"] == f"example-org/{kj('goal', 'show', goal)['project']}",
           f"PR #{c['pr']} --repo is the goal's github_repo")
    shipped = {s["job_id"]: s for s in ships}
    for j in jobs:
        s = shipped.get(j["id"])
        if s is None:
            continue
        c = kj("job", "show", j["id"])["evidence"]["commit"]
        heads = [x for x in creates if x["sha"] == c]
        ok(heads and heads[0]["head"].startswith("konstant/ship-"),
           f"job {j['display_id']}: its verified commit went up as {heads[0]['head'] if heads else '?'}")
        ok(git_rc(remote, "merge-base", "--is-ancestor", c, "main") == 0,
           f"job {j['display_id']}: the remote main contains {c[:12]}")
    ok(git(remote, "rev-parse", "main") == git(target(goal), "rev-parse", "main"),
       "the local target followed the remote main")
    reverts = [m for m in merges if m.get("revert")]
    ok(len(reverts) == int(kw.get("rollbacks", 0)),
       f"{kw.get('rollbacks', 0)} rollback(s), each a revert merged through its own pull request",
       [m["head"] for m in merges])
    for m in reverts:
        rb = git(remote, "rev-parse", f"{m['merge']}^2")
        n = m["head"].rsplit("-", 1)[-1]
        ok(git(remote, "log", "-1", "--format=%s", rb) == f"konstant: roll back ship {n}",
           f"{m['head']} is the revert commit `konstant: roll back ship {n}`")
    no_force(log)


def p6_refused(kw) -> None:
    """github target, a diff the factory must not push: DECISION, nothing reached the remote."""
    goal, log, remote, why = kw["goal"], kw["log"], kw["remote"], kw["reason"]
    jobs = goal_jobs(goal)
    ok(jobs[0]["status"] == "verified", f"job {jobs[0]['display_id']} verified (the work itself "
       "passed)")
    ok(not [s for s in ships_of(jobs) if s["state"] == "shipped"], "nothing shipped")
    rows = escalations_told(goal, "DECISION")
    ok(why in rows[0]["reason"], f"the DECISION names `{why}`", rows[0]["reason"])
    ok(git(remote, "for-each-ref", "--format=%(refname) %(objectname)") == kw["refs_before"],
       "the remote's refs are unchanged")
    ok(gh_calls(log) == [] and lines_of(Path(log + ".push")) == [],
       "the gh stand-in saw no call and no push")
    if kw.get("secret"):
        shape = os.environ.get("FAKE_HARNESS_EXTRA_TEXT", "")
        hay = "".join(lines_of(WS / "var" / "factory" / "events.jsonl")) + json.dumps(inbox())
        ok(shape and shape.split("'")[1] not in hay,
           "the token-shaped string is in no event and no chat line")
    ok(git(target(goal), "rev-parse", "main") == kw["base"], "the target main is unchanged")
    factory_stopped()


def p2(kw) -> None:
    """A producer that overfits the visible DoD: held-out inputs fail, never shipped, BLOCKED."""
    goal = kw["goal"]
    jobs = goal_jobs(goal)
    j = kj("job", "show", jobs[0]["id"])
    ok(j["status"] == "blocked", f"job {j['display_id']} BLOCKED", j["status"])
    ok(len(j["runs"]) == 3, "exactly 3 attempts counted (max_attempts)", len(j["runs"]))
    fails = [v for v in j["verifications"] if v["verdict"] == "FAIL"
             and ((v.get("holdouts") or {}).get("failed") or [])]
    ok(fails and all(h.startswith("H") for v in fails for h in v["holdouts"]["failed"]),
       "verify FAIL: a held-out proof failed while the visible DoD passed",
       [(v["verdict"], (v.get("holdouts") or {}).get("failed")) for v in j["verifications"]])
    told = "".join(p.read_text(errors="replace") for p in
                   (WS / "var" / "factory" / "steps").glob(f"*-attempt-{j['id']}.log"))
    told += json.dumps(inbox(goal))
    ok(re.search(r"holdout H[0-9]+ failed \(hint: ", told),
       "the producer and the owner were told `holdout H<n> failed (hint: ...)`")
    ok(not re.search(r"greet\('Ada'\)|EXPECT_OUT|hello Ada", told),
       "no scenario text (RUN, EXPECT_OUT, the held-out input) in the step logs or the chat")
    ok(all(v["verdict"] != "PASS" for v in j["verifications"]), "never a PASS verdict")
    gens = sorted({(h["generation"], h["state"]) for h in j["holdouts"]})
    ok((1, "retired") in gens and any(g > 1 and st == "sealed" for g, st in gens),
       "the worn set was retired and the scenario writer sealed a fresh one", gens)
    ok(ships_of(jobs) == [], "never shipped")
    ok(git(target(goal), "rev-parse", "main") == kw["base"], "the target tip is unchanged")
    rows = escalations_told(goal, "BLOCKED")
    ok("3 of 3 attempts used" in rows[0]["reason"] or "(round 3)" in rows[0]["reason"],
       "BLOCKED at max_attempts or at the board's max_rounds, whichever came first",
       rows[0]["reason"])
    factory_stopped()


def p3_jail(kw) -> None:
    goal = kw["goal"]
    ok(kj("goal", "show", goal)["intake"] == "none", "with jail = false nothing was taken in")
    ok(goal_jobs(goal) == [] and events(goal) == [], "no job filed, no event")
    ok(len(list((WS / "var" / "runs").iterdir())) == int(kw["runs_before"]),
       "no phase ran (no new run record)")


def p3(kw) -> None:
    """A producer that reads for the holdouts, other tokens and sealed memory: all denied."""
    goal = kw["goal"]
    jobs = goal_jobs(goal)
    log = phase_log(run_dirs({j["id"] for j in jobs}))
    peeks = [ln for ln in log.splitlines() if ln.startswith("peek")]
    ok("peek: var/holdout empty or masked" in peeks and "peek: holdout show refused" in peeks,
       "the sealed store: masked, `holdout show` refused")
    ok(not any(ln.startswith("peek: READ") for ln in peeks), "no scenario was read",
       [x for x in peeks if x.startswith("peek: READ")])
    read = sorted({ln.split()[1] for ln in peeks if ln.startswith("peek-token:") and " READ " in ln})
    ok(read == ["viewer.token", "worker.token"],
       "tokens: only the phase's own (worker) and the read-only viewer token readable", read)
    denied = {ln.split()[1] for ln in peeks if ln.startswith("peek-token:") and "DENIED" in ln}
    ok({"owner.token", "orchestrator.token", "verifier.token", "factory.token",
        "scenario.token", "planner.token"} <= denied, "every other identity's token denied")
    mem = [ln for ln in peeks if ln.startswith("peek-memory:")]
    ok(mem and all(("empty or masked" in ln or "DENIED" in ln) for ln in mem),
       "the memory vault and its index: masked", mem)
    ok(len(mem) >= 2 and (WS / "memory").is_dir(), "(the vault exists outside the jail)")
    for j in jobs:
        v = kj("job", "show", j["id"])["verifications"][-1]
        h = v.get("holdouts") or {}
        ok(v["verdict"] == "PASS" and not h.get("leak") and not h.get("failed"),
           f"job {j['display_id']}: judged honestly, PASS, no leak, no canary in the diff")
    ok(all(s["state"] == "shipped" for s in ships_of(jobs)) and len(ships_of(jobs)) == len(jobs),
       "the honest work after the peek shipped")
    ok(inbox(goal) == [], "nothing escalated")
    factory_stopped()


def p4(kw) -> None:
    """Post-ship failure: rolled back by revert, follow-up filed and shipped, max_rollbacks."""
    goal, b1, b2 = kw["goal"], int(kw["b1"]), int(kw["b2"])
    jobs = goal_jobs(goal)
    ships = ships_of(jobs)
    st = [(s["job_id"], s["state"]) for s in ships]
    ok(len(ships) == 3 and st[0] == (b1, "rolled_back") and st[1][1] == "shipped" and
       st[2] == (b2, "rolled_back"), "ships: B1 rolled back, its follow-up shipped, B2 rolled back",
       st)
    fu = ships[0]["follow_up_id"]
    ok(fu == st[1][0], f"B1's rollback filed follow-up job {fu}, which shipped")
    fuj = kj("job", "show", fu)
    ok("PROBE: test -f {workdir}/README.md" in fuj["acceptance"],
       "the follow-up's DoD carries the failed post-ship probe")
    ok(ships[2]["follow_up_id"] is None, "the second rollback filed no follow-up (max_rollbacks = 1)")
    t = target(goal)
    for s in (ships[0], ships[2]):
        c = s.get("commit") or kj("job", "show", s["job_id"])["evidence"]["commit"]
        ok(git_rc(t, "merge-base", "--is-ancestor", c, "main") == 0,
           f"ship {s['id']}: the shipped commit {c[:12]} is still an ancestor (history kept)")
    pre = ships[2].get("pre")
    if pre:
        ok(git(t, "rev-parse", "main^{tree}") == git(t, "rev-parse", f"{pre}^{{tree}}"),
           "the target tree equals the pre-ship tree after the last rollback")
    ok((t / "README.md").is_file(), "the README the producer deleted is back in the target")
    rows = escalations_told(goal, "BLOCKED")
    ok("max_rollbacks" in rows[0]["reason"], "the BLOCKED names max_rollbacks", rows[0]["reason"])
    evs = [e["event"] for e in events(goal)]
    ok(evs.count("ROLLED_BACK") == 2, "events: two ROLLED_BACK", evs)
    factory_stopped()


def p5a(kw) -> None:
    goal = kw["goal"]
    jobs = goal_jobs(goal)
    j = kj("job", "show", jobs[0]["id"])
    ok(j["status"] == "blocked" and len(j["runs"]) == 3, "the job BLOCKED after its 3rd attempt",
       (j["status"], len(j["runs"])))
    ok(all(x["status"] == "queued" for x in jobs[1:]), "the job after it was never started")
    rows = escalations_told(goal, "BLOCKED")
    ok("3 of 3 attempts used" in rows[0]["reason"], "the one notification names the 3 attempts",
       rows[0]["reason"])
    ok(ships_of(jobs) == [], "nothing shipped")
    factory_stopped()


def p5b(kw) -> None:
    goal = kw["goal"]
    rows = escalations_told(goal, "BUDGET_STOP")
    ok("max_task_runs 2 reached" in rows[0]["reason"], "BUDGET_STOP: max_task_runs 2 reached",
       rows[0]["reason"])
    ok(kj("goal", "show", goal)["status"] == "paused", f"goal {goal} paused")
    jobs = goal_jobs(goal)
    runs = sum(len(kj("job", "show", j["id"])["runs"]) for j in jobs)
    ok(runs == 2, "exactly 2 task runs were started for the goal", runs)
    ok(ships_of(jobs) == [], "nothing shipped")
    factory_stopped()


def owner_wait(kw) -> None:
    goal = kw["goal"]
    jobs = goal_jobs(goal)
    ok(len(jobs) == 2 and all(j["status"] == "queued" for j in jobs), "both jobs filed, queued")
    for j in jobs:
        ok(not [h for h in kj("job", "show", j["id"])["holdouts"] if h["state"] == "sealed"],
           f"job {j['display_id']}: no scenario sealed by a writer (author = owner)")
    rows = escalations_told(goal, "DECISION")
    ok("owner's holdout scenarios" in rows[0]["reason"], "the DECISION asks for the owner's "
       "scenarios", rows[0]["reason"])
    steps = list((WS / "var" / "factory" / "steps").glob(f"*author*{goal}*")) \
        if (WS / "var" / "factory" / "steps").is_dir() else []
    ok(steps == [], "the scenario writer never ran for this goal")


def owner_done(kw) -> None:
    goal = kw["goal"]
    jobs = goal_jobs(goal)
    for j in jobs:
        hs = [h for h in kj("job", "show", j["id"])["holdouts"] if h["state"] == "sealed"]
        ok(len(hs) == 2, f"job {j['display_id']}: the owner's 2 scenarios sealed")
    ok(all(j["status"] == "verified" for j in jobs) and
       all(s["state"] == "shipped" for s in ships_of(jobs)) and len(ships_of(jobs)) == 2,
       "after the owner sealed and acknowledged: both verified and shipped")
    ok(kj("goal", "show", goal)["status"] == "done", f"goal {goal} done")
    factory_stopped()


def chat_all(kw) -> None:
    """Every escalation the factory told (not suppressed) reached the session and was shown in
    exactly one of its later turns; outcomes were summed up."""
    told = [e for e in events() if e["kind"] == "escalation" and not e.get("suppressed")]
    ok(told, f"{len(told)} escalation(s) told during the run")
    posted = inbox()
    ok(sorted(e["id"] for e in posted) == sorted(e["id"] for e in told),
       "every told escalation is in the session's chat inbox, once")
    shown = []
    for log in kw["logs"].split(","):
        for r in map(json.loads, lines_of(Path(log))):
            if " chat turn " in r.get("act", "") and r.get("rc") == 0:
                shown += json.loads(r["out"])["lines"]
    for e in told:
        hit = [ln for ln in shown if ln.startswith(f"konstant {e['event']}: goal {e['goal']}")
               and e["reason"][:60] in ln]
        ok(len(hit) == 1, f"shown once in the chat: {e['event']} {e['goal']}", len(hit))
    ok(any(ln.startswith("konstant outcomes since your last turn") for ln in shown),
       "outcomes came back as summary lines")


LEGS = {"p0": p0, "p1": p1, "p2": p2, "p3": p3, "p3-jail": p3_jail, "p4": p4, "p5a": p5a,
        "p5b": p5b, "p6": p6, "p6-refused": p6_refused, "owner-wait": owner_wait,
        "owner-done": owner_done, "chat-all": chat_all}


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "spec":
        return spec(argv[1:])
    if argv[0] == "turn":
        return turn(argv[1:])
    kw = dict(a.split("=", 1) for a in argv[1:])
    try:
        LEGS[argv[0]](kw)
    except Fail as exc:
        print(f"  CHECK FAILED ({argv[0]}): {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
