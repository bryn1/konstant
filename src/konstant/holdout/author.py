"""The scenario writer's phase (docs/LEVEL5.md 3.4): a job's holdouts written by a model before any
producer exists, then sealed through the same `store.seal()` as `holdout add`.

One phase through the configured harness ([holdout] writer_harness / writer_model, default the
workspace's own: owner decision Q1, one model may play every role), acting as identity `scenario`:
  - input: the goal text, the job's title and brief (its DoD) and the TARGET, read-only, as it is
    now. Never a job clone, a run record, a producer's OUT or log, or any verdict: the jail masks
    var/runs/, every job clone `<project>@<job>`, the target's .audits/, the board DB, the logs
    and var/factory/; the phase reads NO token (it needs no board: konstant seals as `scenario`
    after it) - so it cannot read another job's trail or evidence either;
  - writes: only <store>/<job>/drafts/ (its cwd), bound writable inside the masked store for this
    phase alone; its run dir (prompt, phases/*.log) is <store>/<job>/runs/<stamp>/ and its harness
    home <store>/<job>/home/<harness>/..., deleted after the phase. A harness whose home konstant
    cannot relocate (`command`) is refused: a later producer could read the transcript there;
  - then `seal()`: lint and the negative control on every draft. A refused set goes back to the
    writer ONCE with the reasons (lint reasons name the rule and the id, never content); a second
    refusal escalates `holdout-authoring BLOCKED` (an escalation trail row + a BLOCKED event).
Always confined: without konstant's jail it refuses (`holdouts need a confined phase`).
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from konstant.holdout import store

ROLE = "scenario-writer"
IDENTITY = "scenario"
BLOCKED = "holdout-authoring BLOCKED"


class AuthorRefused(Exception):
    """The scenario phase cannot run here (exit 2) - a setup refusal, not a model's failure."""


def writer_harness(cfg, cat, override: str | None = None):
    """The scenario writer's Harness: the CLI override, else [holdout] writer_harness (+ model),
    else the default; always in factory mode. AuthorRefused when it cannot relocate its home."""
    from konstant import harnesses
    from konstant.gate import harness as harness_mod
    hcfg = dict(cfg.data["harness"])
    h = cfg.data["holdout"]
    name = override or h["writer_harness"] or ""
    if name in harnesses.ADAPTERS and name != "command":
        same = name == hcfg.get("name")
        hcfg = {**hcfg, "name": name, "types": {},
                "command": hcfg["command"] if same else harnesses.DEFAULT_COMMAND,
                "model": h["writer_model"] or (hcfg.get("model", "") if same else "")}
        override = None
    elif not name and h["writer_model"]:
        hcfg = {**hcfg, "model": h["writer_model"], "types": {}}
    else:
        override = name or None          # an argv template (refused below) or the default
    hs = harness_mod.HarnessSet(hcfg, cfg.home, cat, cfg.data["permissions"]["allow"],
                                override=override, jail=bool(cfg.data["gate"]["jail"]),
                                factory=True, conf=cfg.confinement())
    hv = hs.for_agent(ROLE)
    drv = hv.driver()
    if drv is None or not drv.relocatable_home or hv.command is not None:
        name = hv.name if hv.command is None else "command (an argv template)"
        raise AuthorRefused(f"the scenario writer cannot run on {name}: konstant cannot relocate "
                            "that harness's home, so a later producer on it could read the "
                            "scenario writer's transcript (docs/LEVEL5.md 3.4); use claude, codex, "
                            "gemini or dsh ([holdout] writer_harness)")
    if not hv.confines():
        raise AuthorRefused("holdouts need a confined phase: the scenario writer runs only inside "
                            "konstant's jail")
    hv.check()
    return hv, harnesses.adapter(hv.name) if hv.name in harnesses.ADAPTERS else None


def masked(cfg, target: Path) -> list:
    """What the scenario phase must not see besides the sealed store (module docstring)."""
    ws = Path(cfg.home)
    out = [ws / "var" / "runs", ws / "var" / "logs", ws / "var" / "factory",
           ws / "var" / "sessions.json", *(ws / "var" / f for f in ("board.db", "board.db-wal",
                                                                    "board.db-shm")),
           Path(target) / ".audits"]
    for parent in {Path(target).parent, ws / "projects"}:
        if parent.is_dir():
            out += [p for p in parent.iterdir() if "@" in p.name and p.is_dir()]
    return [p for p in out if p.exists()]


def prompt(profile: str, job: dict, goal_text: str, target: Path, drafts: Path, need: int,
           feedback: str = "") -> str:
    head = [f"# konstant scenario writer: job {job['display_id']}", f"KONSTANT-AGENT: {ROLE}",
            f"KONSTANT-JOB: {job['id']}", f"KONSTANT-DRAFTS: {drafts}",
            f"KONSTANT-TARGET: {target}", f"KONSTANT-MIN-SCENARIOS: {need}"]
    body = ["", "## Your profile", profile.strip(), "", "## The goal", goal_text.strip(), "",
            f"## The job: {job['title']}", (job.get("brief") or "").strip(), "",
            "## Your phase",
            f"Write at least {need} scenario files, at least one `KIND: proof`, as "
            f"`<name>.scenario` in {drafts} (your working directory; nothing else is writable). "
            f"The target is {target}: read it to see what exists now (it is read-only). A proof "
            "must FAIL on it as it is now and pass once the job is done; a regression must pass "
            "now and after. Use inputs and expected outputs that the brief above does not "
            "contain. You are a leaf: never spawn agents or sub-sessions."]
    if feedback:
        body += ["", "## Your previous drafts were refused; fix every reason", feedback]
    return "\n".join(head + body) + "\n"


def _fresh(d: Path) -> Path:
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, mode=0o700)
    return d


def author(cfg, cat, job: dict, goal_text: str, target: Path, client, need: int,
           override: str | None = None, log=print) -> dict:
    """Run the scenario phase for `job` (a board job dict) and seal its drafts as `scenario`.
    -> {"sealed": [rows], "attempts": n} or {"blocked": reason, "attempts": n}.
    AuthorRefused for a setup refusal (no jail, a non-relocatable harness)."""
    from konstant.agents.generate import Generator
    from konstant.memory import view
    from konstant.verify.holdout import confined
    why = confined(cfg)
    if why:
        raise AuthorRefused(why)
    harness, _ad = writer_harness(cfg, cat, override)
    jd = store.job_dir(cfg, job["id"])
    for d in (jd.parent, jd):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(d, 0o700)
    profile = Generator(cat, Path(cfg.home)).agent_prompt(ROLE)      # one snapshot (F-08)
    feedback, reasons = "", []
    for attempt in (1, 2):
        drafts = _fresh(jd / "drafts")
        home = _fresh(jd / "home")
        run_dir = jd / "runs" / f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-a{attempt}"
        run_dir.mkdir(parents=True, mode=0o700)
        text = prompt(profile, job, goal_text, target, drafts, need, feedback)
        # memory (owner decision 2026-11-08): it reads the shared pool through an exported copy and
        # writes only the sealed pool, collected below; its phase still holds no token
        mem_env = view.prepare(client, drafts) if cfg.data["memory"]["enabled"] else {}
        log(f"konstant holdout: scenario writer for job {job['display_id']} (attempt {attempt}, "
            f"{harness.name}; run dir {run_dir})")
        res = harness.run(text, agent=ROLE, cwd=drafts, run_dir=run_dir,
                          label=f"scenario-a{attempt}", out=None, identity=IDENTITY,
                          home_base=home, tokens=(), hide=tuple(masked(cfg, target)),
                          extra_env=mem_env)
        shutil.rmtree(home, ignore_errors=True)
        if mem_env:
            view.collect(client, drafts, log)
        files = sorted(p for p in drafts.glob("*.scenario") if p.is_file() and not p.is_symlink())
        if res.rc != 0 and not files:
            reasons = [f"the scenario writer exited {res.rc} and wrote no draft"]
        elif not files:
            reasons = ["the scenario writer wrote no `*.scenario` draft"]
        else:
            try:
                rows = store.seal(cfg, client, str(job["id"]), [str(f) for f in files],
                                  drafts=drafts)
                shutil.rmtree(drafts, ignore_errors=True)
                return {"sealed": rows, "attempts": attempt}
            except store.SealRefused as exc:
                if exc.code != 1:
                    raise AuthorRefused("; ".join(exc.lines)) from None
                reasons = exc.lines
        feedback = "\n".join(f"- {r}" for r in reasons)
        log(f"konstant holdout: job {job['display_id']} drafts refused: "
            + "; ".join(reasons)[:400])
    shutil.rmtree(jd / "drafts", ignore_errors=True)
    codes = sorted({r.split(":", 1)[0] for r in reasons})
    return {"blocked": f"{BLOCKED}: job {job['display_id']}: the scenario writer's drafts were "
                       f"refused twice ({', '.join(codes)})", "attempts": 2}
