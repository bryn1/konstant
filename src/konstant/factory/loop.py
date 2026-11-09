"""`konstant factory run` (docs/LEVEL5.md 6.1): the factory loop. Code only; no model decides.

One factory per workspace (factory/proc.py: an flock, a pid-checked pid file). Each tick:
  1. the kill switch (var/factory/STOP, `factory stop`) or a signal: start nothing new, let the
     running steps finish (graceful drain), exit;
  2. a halt (the board's factory_log) or an undelivered event in var/factory/spool/: stop
     (`notifier failed: factory halted`, exit 4): no dark factory keeps working unheard;
  3. in-flight ships reconciled against their targets (factory/reconcile.py);
  4. the board read and planned (factory/steps.py); per goal its budget checked (6.2): exhausted
     -> the goal paused + BUDGET_STOP;
  5. the actions run: inline board transitions (approve, exhaust, escalate, done) and steps as
     child processes of konstant's own verbs (`intake`, `holdout author`, `task run --job`,
     `verify`, `ship`), at most cap model steps at once (triage/tiers.py cap_of: [harness]
     max_concurrency / max_parallel), jobs of one project serially, one ship at a time;
  6. the heartbeat (var/factory/heartbeat.json) and the stall check: no progress for
     [factory] stall_after_s while work is ready or running -> a BLOCKED escalation.
Every step is an idempotent board transition or a konstant verb with its own guards, so a factory
killed anywhere resumes from the board alone. Attempts are charged before a run starts.
Exit (--until-idle): 0 every goal done, 4 a goal ended in an escalation (or the factory halted),
2 refused before the start, 5 an internal error (escalated HALTED, the factory halted).
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

from konstant.client import Client, ClientError, token_for
from konstant.factory import budget, health, notify, proc, steps
from konstant.factory.proc import Step

EXIT_OK, EXIT_REFUSED, EXIT_ESCALATED, EXIT_ERROR = 0, 2, 4, 5
NOTIFIER_FAILED = "notifier failed: factory halted"


class Refused(Exception):
    """A refusal before the start (exit 2)."""


class Factory:
    def __init__(self, cfg, goals=(), mode: str = "forever", harness: str | None = None,
                 log=None):
        self.cfg, self.home = cfg, Path(cfg.home)
        self.only, self.mode, self.harness = list(goals), mode, harness
        self.log = log or (lambda m: print(m, file=sys.stderr, flush=True))
        f = cfg.data["factory"]
        self.tick_s, self.stall_s = int(f["tick_s"]), int(f["stall_after_s"])
        from konstant.triage import tiers
        self.cap = tiers.cap_of(cfg.data["harness"])[0]
        self.running: list = []
        self.ticks, self.stopping, self.signals = 0, "", 0
        self.progress_at, self.fp, self.ready = time.time(), "", 0
        self.states: dict = {}
        self.factory = self.viewer = None

    # --- setup ----------------------------------------------------------------------------------
    def client(self, label: str) -> Client:
        return Client(self.cfg.base_url, token_for(self.cfg, label), timeout=30)

    def considered(self) -> list:
        goals = self.viewer.get("/api/goals")["goals"]
        if self.only:
            known = {g["slug"]: g for g in goals}
            missing = [s for s in self.only if s not in known]
            if missing:
                raise Refused(f"no goal {', '.join(missing)}")
            return [known[s] for s in self.only]
        return [g for g in goals if g["status"] in ("active", "paused", "done")]

    def preflight(self) -> None:
        from konstant import harnesses, integrity
        from konstant.gate import harness as harness_mod
        from konstant.verify.holdout import UNCONFINED, confined
        self.factory, self.viewer = self.client("factory"), self.client("viewer")
        h = self.factory.get("/api/factory/halt")
        if h["halted"]:
            raise Refused(f"the factory is halted since {h['since']} ({h['reason']}): `konstant "
                          "--as owner factory resume`")
        if notify.spooled(self.home):
            raise Refused(f"{len(notify.spooled(self.home))} undelivered event(s) in "
                          "var/factory/spool/: `konstant --as owner factory resume` delivers them")
        for g in self.considered():          # an unmeasurable budget refuses the start (6.2)
            why = budget.unmeasurable(self.cfg, g["spec"], self.harness)
            if why:
                raise Refused(why)
        why = confined(self.cfg) or integrity.require(self.cfg)
        if why:
            raise Refused(why)
        from konstant import catalog as catalog_mod
        cat = catalog_mod.load(catalog_mod.find_root(self.cfg.home,
                                                     self.cfg.data["catalog"]["path"]))
        over = None
        if self.harness:
            from konstant.cli.task_run import cli_template
            over = self.harness if self.harness in harnesses.ADAPTERS else \
                cli_template(self.harness)
        hs = harness_mod.HarnessSet(self.cfg.data["harness"], self.cfg.home, cat,
                                    self.cfg.data["permissions"]["allow"], override=over,
                                    jail=bool(self.cfg.data["gate"]["jail"]), factory=True,
                                    conf=self.cfg.confinement())
        loose = hs.unconfined()
        if loose:
            raise Refused(f"{UNCONFINED}: the harness(es) {', '.join(loose)} would not run in "
                          "konstant's jail")
        try:
            hs.check()
        except harness_mod.HarnessError as exc:
            raise Refused(str(exc)) from None

    # --- one tick -------------------------------------------------------------------------------
    def board(self) -> steps.Planner:
        v = self.viewer
        goals = self.considered()
        for g in goals:
            g["view"] = v.get(f"/api/factory/goals/{g['slug']}") if g["status"] == "active" \
                else None
        ids = sorted({j["id"] for g in goals for j in (g.get("view") or {}).get("jobs", [])})
        jobs = {}
        for jid in ids:
            jobs[jid] = v.get(f"/api/jobs/{jid}", trail="true")
        ships = v.get("/api/ships")["ships"]
        esc = v.get("/api/factory/escalations", open="true")["escalations"]
        halted = v.get("/api/factory/shipping")["shipping"] == "halted"
        need = {jid: self.need(jobs[jid], goals) for jid in jobs}
        running = {s.action.key() for s in self.running}
        p = steps.Planner(goals, jobs, ships, esc, halted, running, need, self.locked)
        p.projects = {s.action.project for s in self.running
                      if s.action.kind in ("attempt", "verify", "ship")}
        p.goal_list = goals
        return p

    def need(self, job: dict, goals: list) -> int:
        g = next((g for g in goals if g["id"] == job.get("goal_id")), None)
        per = (g["spec"]["holdout"]["min_per_job"] if g else 0) or 0
        return max(per, self.cfg.data["holdout"]["min_per_job"])

    def locked(self, job: dict) -> bool:
        if not job.get("workdir"):
            return False
        from konstant.cli.task_run import project_lock
        fh = project_lock(self.home, self.cfg.resolve(job["workdir"]))
        if fh is None:
            return True
        if fh is not True:
            fh.close()
        return False

    def plan(self) -> tuple:
        p = self.board()
        acts = []
        for g in p.goal_list:
            mine = p.goal_actions(g)
            view = g.get("view") or {}
            if any(a.kind == "attempt" for a in mine) and view.get("exhausted"):
                mine = [a for a in mine if a.kind != "attempt"] + [steps.Action(
                    "budget", g["slug"], reason="; ".join(view["exhausted"]))]
            acts += mine
        self.states = p.state
        return p, acts

    def tick(self) -> int:
        """Run one tick; -> how many actions it carried out."""
        self.ticks += 1
        if not any(s.action.kind == "ship" for s in self.running):
            from konstant.factory import reconcile
            reconcile.reconcile(self.cfg, self.factory, self.log)
        _p, acts = self.plan()
        self.ready = sum(1 for a in acts if a.kind in steps.STEP_KINDS)
        did = 0
        for a in acts:
            if self.stopping:
                break
            did += self.act(a)
            if notify.spooled(self.home):
                break
        return did

    def act(self, a: steps.Action) -> int:
        f = self.factory
        if a.kind == "approve":
            f.post(f"/api/jobs/{a.job}/approve")
            self.log(f"konstant factory: approved job {a.display_id} (intake had stopped after "
                     "filing it)")
            return 1
        if a.kind == "escalate":
            notify.emit(self.cfg, a.event, a.goal, a.job, a.display_id, a.reason, client=f)
            return 1
        if a.kind == "exhaust":
            f.post(f"/api/factory/jobs/{a.job}/exhausted", {"reason": a.reason})
            notify.emit(self.cfg, "BLOCKED", a.goal, a.job, a.display_id,
                        f"job {a.display_id}: {a.reason} (max_attempts)", client=f)
            return 1
        if a.kind == "budget":
            f.post(f"/api/goals/{a.goal}/pause")
            notify.emit(self.cfg, "BUDGET_STOP", a.goal, reason=f"budget: {a.reason}; the goal "
                        "is paused (`goal resume` after `factory ack`)", client=f)
            return 1
        if a.kind == "done":
            f.post(f"/api/factory/goals/{a.goal}/done")
            notify.emit(self.cfg, "GOAL_DONE", a.goal, reason=a.reason, client=f)
            return 1
        return self.spawn(a)

    def spawn(self, a: steps.Action) -> int:
        model = sum(1 for s in self.running if s.action.kind in steps.MODEL_STEPS)
        if a.kind in steps.MODEL_STEPS and model >= self.cap:
            return 0
        if a.kind == "ship" and any(s.action.kind == "ship" for s in self.running):
            return 0
        if a.kind in ("attempt", "verify", "ship") and any(
                s.action.project == a.project and s.action.kind in ("attempt", "verify", "ship")
                for s in self.running):
            return 0                       # jobs of one project serially, also within a tick
        k = [sys.executable, "-m", "konstant"]
        over = ["--harness", self.harness] if self.harness else []
        argv = {"intake": k + ["intake", a.goal] + over,
                "author": k + ["holdout", "author", str(a.job)] + over,
                "verify": k + ["verify", str(a.job)],
                "ship": k + ["ship", str(a.job)]}.get(a.kind)
        if a.kind == "attempt":
            job = self.viewer.get(f"/api/jobs/{a.job}")
            stamp = time.time_ns()
            for kind in ("attempts", "task_runs"):         # charged BEFORE the run starts
                self.factory.post("/api/factory/ledger", {
                    "goal": a.goal, "job": a.job, "kind": kind, "amount": 1,
                    "ref": f"{kind}:{a.job}:{stamp}"})
            argv = k + ["task", "run", job["title"], "--job", str(a.job), "--type",
                        job["type"]] + over
        env = {k2: v for k2, v in os.environ.items()
               if k2 not in ("KONSTANT_IN_TASK", "KONSTANT_CHAT_SESSION", "KONSTANT_ROLE")}
        env["KONSTANT_HOME"] = str(self.home)
        name = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{self.ticks}-{a.kind}-" \
               f"{a.job or a.goal}.log"
        st = Step(a, argv, self.home / "var" / "factory" / "steps" / name, env, self.home)
        self.running.append(st)
        self.log(f"konstant factory: {a.kind} {('job ' + a.display_id) if a.job else a.goal} "
                 f"({a.reason}) pid {st.proc.pid}, log {st.log}")
        return 1

    def reap(self) -> int:
        done = 0
        for st in list(self.running):
            rc = st.poll()
            if rc is None:
                continue
            self.running.remove(st)
            done += 1
            self.finished(st, rc)
        return done

    def finished(self, st: Step, rc: int) -> None:
        a = st.action
        self.log(f"konstant factory: {a.kind} {('job ' + a.display_id) if a.job else a.goal} "
                 f"exited {rc}")
        if a.kind in ("attempt", "intake"):
            self.charge_runs(st.started, a)
        last = (st.tail(1) or [f"exit {rc}"])[0][-300:]
        if a.kind == "author" and rc != 0:
            notify.emit(self.cfg, "BLOCKED", a.goal, a.job, a.display_id,
                        f"holdout authoring: {last}", client=self.factory)
        elif a.kind == "intake" and rc not in (0, 3, 4):
            notify.emit(self.cfg, "BLOCKED", a.goal, reason=f"intake exited {rc}: {last}",
                        client=self.factory)
        elif a.kind == "ship" and rc in (1, 2):
            esc = self.viewer.get("/api/factory/escalations", open="true")["escalations"]
            if not any(e.get("job_id") == a.job for e in esc):
                notify.emit(self.cfg, "BLOCKED", a.goal, a.job, a.display_id,
                            f"ship refused: {last}", client=self.factory)

    def charge_runs(self, since: float, a: steps.Action) -> None:
        runs = self.home / "var" / "runs"
        for d in sorted(runs.iterdir()) if runs.is_dir() else []:
            try:
                if d.stat().st_mtime < since - 1:
                    continue
                rec = json.loads((d / "record.json").read_text())
            except (OSError, ValueError):
                continue
            if a.kind == "attempt" and str(rec.get("job")) != str(a.job):
                continue
            if a.kind == "intake" and rec.get("goal") != a.goal:
                continue
            for kind, amount in budget.run_charges(self.cfg, d).items():
                self.factory.post("/api/factory/ledger", {
                    "goal": a.goal, "job": a.job, "kind": kind, "amount": amount,
                    "ref": f"run:{d.name}:{kind}"})

    # --- the loop -------------------------------------------------------------------------------
    def on_signal(self, signum, _frame) -> None:
        self.signals += 1
        self.stopping = self.stopping or f"stopped by {signal.Signals(signum).name}"
        if self.signals > 1:
            for st in self.running:
                if st.action.kind != "ship":
                    try:
                        st.proc.send_signal(signal.SIGTERM)
                    except OSError:
                        pass

    def halt(self, reason: str) -> None:
        try:
            self.factory.post("/api/factory/halt", {"action": "halt", "reason": reason})
        except ClientError:
            pass
        notify.local(self.cfg, f"HALTED -: {reason}")

    def drain(self, why: str) -> None:
        self.log(f"konstant factory: {why}: no new steps; waiting for {len(self.running)} "
                 "running step(s)")
        while self.running:
            health.heartbeat(self, "draining")
            self.reap()
            time.sleep(0.5)

    def sleep(self) -> None:
        end = time.time() + self.tick_s
        while time.time() < end and not self.stopping:
            if self.reap():
                return
            if proc.stop_file(self.home).exists():
                return
            time.sleep(0.2)

    def run(self) -> int:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self.on_signal)
        try:
            return self._run()
        except Exception as exc:  # noqa: BLE001 - a factory that does not understand its state
            why = f"internal error: {type(exc).__name__}: {exc}"[:400]
            try:
                self.halt(why)
                notify.emit(self.cfg, "HALTED", reason=why + "; the factory is halted until "
                            "`konstant --as owner factory resume`", client=self.factory)
            except Exception:  # noqa: BLE001 - the halt line is on stderr and in notify.log
                pass
            for st in self.running:
                st.poll()
            return EXIT_ERROR

    def _run(self) -> int:
        while True:
            if proc.stop_file(self.home).exists() and not self.stopping:
                self.stopping = "the kill switch is set (var/factory/STOP)"
            if self.stopping:
                self.drain(self.stopping)
                health.heartbeat(self, "stopped")
                self.log(f"konstant factory: stopped ({self.stopping})")
                return EXIT_OK
            if notify.spooled(self.home):
                self.halt(NOTIFIER_FAILED + f": {notify.spooled(self.home)[0].get('undelivered')}")
                self.log(f"konstant factory: {NOTIFIER_FAILED}")
                self.stopping = NOTIFIER_FAILED
                for st in self.running:
                    if st.action.kind != "ship":
                        st.proc.send_signal(signal.SIGTERM)
                self.drain(NOTIFIER_FAILED)
                health.heartbeat(self, "halted")
                return EXIT_ESCALATED
            self.reap()
            did = self.tick()
            if notify.spooled(self.home):
                continue
            health.check_stall(self, health.fingerprint(self))
            health.heartbeat(self, "running")
            if self.mode == "once":
                self.drain("--once: this tick's steps")
                health.heartbeat(self, "stopped")
                return EXIT_OK
            if self.mode == "until_idle" and not self.running and did == 0:
                done = all(v == "done" for v in self.states.values())
                health.heartbeat(self, "stopped")
                self.log("konstant factory: idle: " + (", ".join(
                    f"{k} {v}" for k, v in sorted(self.states.items())) or "no goals"))
                return EXIT_OK if done else EXIT_ESCALATED
            if did == 0:
                self.sleep()
