"""Phase runner (DESIGN §6.5): konstant, not the model, drives the phases of a typed task.

For each phase: build the prompt (agent profile + phase brief), snapshot OUT (path -> sha256),
run the harness, kill every process the phase left behind (gate/reaper.py), snapshot again, write
`phases/<n>-<agent>-c<cycle>.json` (created / modified / deleted, the sha256 of each verdict file
it left, exit code, duration). Consecutive `parallel: true` phases run concurrently (up to
[harness] max_parallel); inside such a group konstant cannot tell which process wrote a file, so
the group shares one before/after snapshot and a verdict file is credited by NAME to the group
member it names. `max_parallel = 1` runs every phase as its own group: strict per-phase
attribution (REVIEW F-15).
Agent profiles are composed ONCE, when the runner starts, and kept in memory (and in
`profiles/` of the run dir): a phase that edits catalog/ cannot change what a later phase is told
(REVIEW F-08).
Back-edge: a FAIL/FIX/RECONSIDER verdict re-runs the producers with the verdict text, then every
verifying phase run so far (each writing a new `-c<n>` file), up to [gate] max_cycles.
"""
from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from konstant.gate import reaper
from konstant.gate.rules.common import CACHE_DIRS, Run, cycle_name, is_verdict_file, verdict_word
from konstant.gate.rules.verdicts import project_changed

ORCHESTRATOR = "orchestrator"


def all_words(rec: dict) -> str:
    return "|".join(w for ws in rec["verdict_words"].values() for w in ws)


def snapshot(out: Path) -> dict:
    snap = {}
    if out.is_dir():
        for root, dirs, files in os.walk(out):
            dirs[:] = [d for d in dirs if d not in CACHE_DIRS and d != ".tmp"]
            for fn in files:
                p = Path(root) / fn
                try:
                    snap[os.path.relpath(p, out)] = hashlib.sha256(p.read_bytes()).hexdigest()
                except OSError:
                    pass
    return snap


def diff(before: dict, after: dict) -> dict:
    return {"created": sorted(set(after) - set(before)),
            "modified": sorted(k for k in after if k in before and after[k] != before[k]),
            "deleted": sorted(set(before) - set(after))}


def groups(phases: list) -> list:
    out = []
    for p in phases:
        if p.get("parallel") and out:
            out[-1].append(p)
        else:
            out.append([p])
    return out


HOLDOUT_NOTE = ("This job has {n} sealed holdout scenario(s): black-box acceptance checks written "
                "before this work, stored where no phase can read them, and run only by "
                "konstant's verifier, without network, on the commit the job closes with. A "
                "failing one reveals only its id and a one-line hint. Build what the DoD asks for "
                "in general; never special-case an example. If you believe a holdout contradicts "
                "the DoD, write `DISPUTE | H<n> | <why>` in DONE.md: the owner decides; it "
                "excuses nothing.")


class PhaseRunner:
    def __init__(self, rec: dict, cat, harness, *, run_dir: Path, max_parallel: int = 2,
                 acceptance: str = "", log=print, isolate: bool = False):
        self.rec, self.cat, self.harness = rec, cat, harness
        self.run_dir, self.out = Path(run_dir), Path(rec["out"])
        self.max_parallel = max(1, int(max_parallel))
        self.acceptance, self.log = acceptance, log
        self.runs: dict = {}           # phase n -> number of runs so far
        self.seq = 0
        self.cycles: list = []         # rows for CYCLES.md
        # an intake run (no project: the target is read-only to it) works in OUT (LEVEL5 4.2)
        self.cwd = Path(rec.get("cwd") or rec.get("project") or rec["workspace"])
        self.isolate = isolate and reaper.become_subreaper()   # only the `task run` process
        agents = dict.fromkeys([p["agent"] for p in rec.get("phases", [])] + [ORCHESTRATOR])
        self.profiles = {a: self._compose(a) for a in agents}       # the snapshot (F-08)
        d = self.run_dir / "profiles"
        d.mkdir(parents=True, exist_ok=True)
        for a, text in self.profiles.items():
            (d / f"{a}.md").write_text(text, encoding="utf-8")

    # --- prompt ---------------------------------------------------------------------------
    def _compose(self, agent: str) -> str:
        """The composed profile (role + contract + base doctrine + skills), as `agents sync`
        writes it to .claude/agents/<agent>.md, minus the frontmatter."""
        from konstant.agents.generate import GenerateError, Generator
        try:
            return Generator(self.cat, Path(self.rec["workspace"])).agent_prompt(agent)
        except (GenerateError, KeyError, OSError):
            return f"You are the {agent} agent of a konstant workspace."

    def profile(self, agent: str) -> str:
        if agent not in self.profiles:
            self.profiles[agent] = self._compose(agent)
        return self.profiles[agent]

    def groups(self, phases: list) -> list:
        return [[p] for p in phases] if self.max_parallel == 1 else groups(phases)

    def dod_rows(self) -> list:
        from konstant.board.dod import dod_rows
        return dod_rows(self.rec.get("acceptance") or "") if self.rec.get("job") else []

    def prompt(self, phase: dict, verdict_file, feedback: str, closeout: bool) -> str:
        r = self.rec
        head = [f"# konstant phase {phase.get('n', '-')}: {phase['agent']}"
                + (f" ({phase['step']})" if phase.get("step") else ""),
                f"KONSTANT-AGENT: {phase['agent']}", f"KONSTANT-STEP: {phase.get('step') or '-'}",
                f"KONSTANT-TYPE: {r['type']}", f"KONSTANT-OUT: {r['out']}",
                f"KONSTANT-PROJECT: {r.get('project') or '-'}",
                f"KONSTANT-VERDICT: {verdict_file or '-'}", f"KONSTANT-JUDGE: {r['judge_cmd']}",
                f"KONSTANT-CYCLE: {self.runs.get(phase.get('n'), 0) + 1}"]
        if r.get("job"):
            head.append(f"KONSTANT-JOB: {r['job']}")
        if "holdouts" in r:
            head.append(f"KONSTANT-HOLDOUTS: {r['holdouts']}")
        for key in ("goal", "target", "max_jobs"):          # an intake run (LEVEL5 4.2)
            if r.get("intake") and r.get(key) not in (None, ""):
                head.append(f"KONSTANT-{key.upper().replace('_', '-')}: {r[key]}")
        head += [f"KONSTANT-CYCLE-ROW: {row}" for row in (self.cycles if closeout else [])]
        head += [f"KONSTANT-DOD-ROW: DoD-{i} | {row}"
                 for i, row in enumerate(self.dod_rows() if closeout else [], 1)]
        body = ["", "## Your profile", self.profile(phase["agent"]).strip(), "",
                "## The task", r["task"]]
        if self.acceptance:
            body += ["", "## Definition of Done", self.acceptance]
        if "holdouts" in r:
            body += ["", "## Holdouts", HOLDOUT_NOTE.format(n=r["holdouts"])]
        body += ["", "## Your phase", phase.get("task") or "",
                 "You are a leaf: never spawn agents or sub-sessions. Work in the project "
                 f"directory; OUT is {r['out']}; scratch goes under OUT/.tmp/."]
        if closeout:
            body += ["Write DONE.md in OUT (`ID | claim | STATUS | evidence` per DoD claim, plus "
                     "the CLEANUP line) and CYCLES.md (`cycle | trigger | action | outcome`, one "
                     "row per KONSTANT-CYCLE-ROW above), from the artifacts in OUT. Never write "
                     "or edit a verdict file."]
            if self.dod_rows():
                body += ["DONE.md carries one row per KONSTANT-DOD-ROW above, with its ID "
                         "(`DoD-<n> | <claim> | PASS or BLOCKED | <evidence>`); a DoD row is "
                         "never N/A."]
        elif verdict_file:
            body += [f"Write your verdict to OUT/{verdict_file}: findings, then as your LAST step "
                     f"run `{r['judge_cmd']}` and put its printed `# JUDGED:` line directly above "
                     f"the final line `# VERDICT: {all_words(r)}`. Never "
                     "write or edit any other verdict file."]
        else:
            body += ["Produce your part of the deliverable and commit it. Never write a verdict "
                     "file (any *verdict*.md): verdicts belong to the verifying phases."]
        if feedback:
            body += ["", "## Feedback to act on", feedback]
        return "\n".join(head + body) + "\n"

    # --- running ----------------------------------------------------------------------------
    def _target(self, phase: dict):
        if not phase.get("verdict"):
            return None
        return cycle_name(phase["verdict"], self.runs.get(phase["n"], 0) + 1)

    def run_group(self, group: list, feedback: str = "", closeout: bool = False) -> list:
        """Run one group of phases; returns their manifests."""
        jobs = []
        for ph in group:
            target = None if closeout else self._target(ph)
            self.seq += 1
            cyc = self.runs.get(ph["n"], 0) + 1
            label = f"{self.seq:02d}-{ph['n']}-{ph['agent']}-c{cyc}"
            jobs.append((ph, target, label, cyc, self.prompt(ph, target, feedback, closeout)))
        before = snapshot(self.out)

        def one(job):
            ph, _t, label, _c, prompt = job
            self.log(f"konstant task: phase {label} ...")
            return self.harness.run(prompt, agent=ph["agent"], cwd=self.cwd,
                                    run_dir=self.run_dir, label=label, out=self.out,
                                    identity=self.identity(ph, closeout))

        if len(jobs) == 1:
            results = [one(jobs[0])]
        else:
            with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(jobs))) as ex:
                results = list(ex.map(one, jobs))
        left = reaper.kill_leftovers() if self.isolate else 0
        if left:
            self.log(f"konstant task: phase {jobs[0][2]}{' group' if len(jobs) > 1 else ''} left "
                     f"{left} process(es) running; killed them")
        after = snapshot(self.out)
        changes = diff(before, after)
        shas = {n: after[n] for n in changes["created"] + changes["modified"]
                if is_verdict_file(Path(n))}
        verdicts = [t for _p, t, _l, _c, _pr in jobs if t]
        manifests = []
        for (ph, target, label, cyc, _pr), res in zip(jobs, results):
            self.runs[ph["n"]] = cyc
            m = {"n": ph["n"], "agent": ph["agent"], "step": ph.get("step"), "cycle": cyc,
                 "label": label, "verdict": target, "closeout": closeout, "rc": res.rc,
                 "seconds": res.seconds, "timed_out": res.timed_out, "log": res.log, **changes,
                 "shas": shas, "left_running": left, **self._harness_of(ph["agent"]),
                 "identity": self.identity(ph, closeout)}
            if len(jobs) > 1:
                m["group"] = [j[2] for j in jobs]
                m["group_verdicts"] = verdicts
            (self.run_dir / "phases").mkdir(parents=True, exist_ok=True)
            (self.run_dir / "phases" / f"{label}.json").write_text(json.dumps(m, indent=2))
            manifests.append(m)
            if res.rc != 0:
                self.log(f"konstant task: phase {label} exited {res.rc} (log {res.log})")
        return manifests

    def identity(self, phase: dict, closeout: bool = False) -> str:
        """The identity a phase acts as (catalog: worker unless the type or phase names a factory
        identity; the close-out acts as the type's own identity)."""
        if closeout:
            return self.cat.identity(self.rec["type"]) if self.cat is not None else "worker"
        return phase.get("identity") or "worker"

    def _harness_of(self, agent: str) -> dict:
        h = self.harness.for_agent(agent) if hasattr(self.harness, "for_agent") else self.harness
        return {"harness": getattr(h, "name", "command"), "model": getattr(h, "model", "")}

    def verdict_of(self, phase: dict):
        """(word, file) of the phase's newest verdict file, after its last run."""
        n = self.runs.get(phase["n"], 0)
        if not n or not phase.get("verdict"):
            return None, None
        f = self.out / cycle_name(phase["verdict"], n)
        return (verdict_word(f) if f.is_file() else None), f

    # --- the phase plan + back-edge ---------------------------------------------------------
    def run_all(self, max_cycles: int) -> None:
        rec, cat = self.rec, self.cat
        fail_words = set((rec.get("verdict_words") or cat.verdict_words())["fail"])
        phases = rec["phases"]
        is_prod = {p["n"]: cat.is_producer(rec["type"], p) for p in phases}
        producers = self.groups([p for p in phases if is_prod[p["n"]]])
        ran_verifiers: list = []
        cycle, row_action = 1, "ran the phases in order"
        for g in self.groups(phases):
            g = [p for p in g if self._wanted(p)]
            if not g:
                continue
            self.run_group(g)
            if all(is_prod[p["n"]] or not p.get("verdict") for p in g):
                continue
            ran_verifiers.append([p for p in g if not is_prod[p["n"]]])
            while True:
                failing = [(p, *self.verdict_of(p)) for p in g if p.get("verdict")]
                failing = [(p, w, f) for p, w, f in failing if w in fail_words]
                if not failing or cycle >= max_cycles:
                    break
                fb = "\n\n".join(f"### {f.name}\n{f.read_text(errors='replace')[-3000:]}"
                                 for _p, _w, f in failing)
                trig = ", ".join(f"{f.name} {w}" for _p, w, f in failing)
                self.cycles.append(f"{cycle} | {'start' if cycle == 1 else 'back-edge'} | "
                                   f"{row_action} | {trig}")
                cycle += 1
                row_action = "re-ran the producers with the verdict, then the verifiers"
                for pg in producers:
                    self.run_group(pg, feedback=fb)
                for vg in ran_verifiers:
                    self.run_group(vg)
        words = [self.verdict_of(p)[0] for p in phases if p.get("verdict") and self.runs.get(p["n"])]
        outcome = ", ".join(f"{w or 'none'}" for w in words) or "no verdicts"
        self.cycles.append(f"{cycle} | {'start' if cycle == 1 else 'back-edge'} | {row_action} | "
                           f"{outcome}")

    def _wanted(self, phase: dict) -> bool:
        if phase.get("when") != "changed":
            return True
        if phase.get("step") == "open":
            return False         # read-only types: nothing is known to change before the work
        return project_changed(Run(run_dir=self.run_dir, rec=self.rec))

    def closeout(self, feedback: str = "") -> list:
        ph = {"n": 0, "agent": ORCHESTRATOR, "step": None, "verdict": None,
              "task": "close-out: write DONE.md and CYCLES.md from the artifacts"}
        return self.run_group([ph], feedback=feedback, closeout=True)

    def rerun_producers(self, feedback: str) -> None:
        phases = self.rec["phases"]
        for g in self.groups([p for p in phases if self.cat.is_producer(self.rec["type"], p)]):
            self.run_group(g, feedback=feedback)
        self.rerun_verifiers()

    def rerun_verifiers(self, only: str | None = None) -> None:
        phases = [p for p in self.rec["phases"] if p.get("verdict") and self.runs.get(p["n"])
                  and not self.cat.is_producer(self.rec["type"], p)
                  and (only is None or p["verdict"] == only)]
        for g in self.groups(phases):
            self.run_group(g)
