"""The factory as a long-lived process (docs/LEVEL5.md 6.1, 6.4, 6.6; wave L5-5).

  D7    `factory start` twice: the second exits 2 `a factory already runs (pid ...)`; `factory
        stop` -> `factory status` stopped
  kill switch  a running factory drains on var/factory/STOP (its running step finishes, nothing
        new starts) and no factory starts while it is set; `factory resume` clears it
  crash  a factory killed (SIGKILL, with its steps) mid-attempt resumes from the board: the same
        goal runs to done, the killed attempt counted
  D6    the factory view: /api/factory/goals/greeter with the viewer token carries budget, jobs,
        ships, escalations and no scenario text
  stall  no progress for [factory] stall_after_s while work runs -> one BLOCKED `factory stalled`
  health a hung loop's heartbeat goes stale: `factory status` and `doctor` say so
  unit  `factory install-unit` writes a systemd --user unit and never enables or starts it
Each refusal has a _red and a _green test."""
from __future__ import annotations

import json
import os
import signal
import time
import urllib.request

from tests.factory.loopkit import (diagnose, events, factory, jobs, kill_group, make_lws,
                                   notify_lines, start_bg, wait_for)
from tests.holdout.conftest import needs_jail


def status(s) -> dict:
    return s.w.json("factory", "status")


def heartbeat(s) -> dict:
    p = s.w.home / "var" / "factory" / "heartbeat.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def test_D7_second_factory_refused_red_then_stop_and_start_green(tmp_path):
    s = make_lws(tmp_path, goal=False)
    try:
        r1 = s.w.run("factory", "start")
        assert r1.returncode == 0 and "factory started (pid" in r1.stdout, r1.stderr
        pid = int(r1.stdout.split("pid ")[1].split(")")[0])
        r2 = s.w.run("factory", "start")                                     # red
        assert r2.returncode == 2 and f"a factory already runs (pid {pid})" in r2.stderr, r2
        r3 = factory(s, "run", "--until-idle")                               # red, foreground
        assert r3.returncode == 2 and "a factory already runs" in r3.stderr
        assert status(s)["state"] == "running"
        r = s.w.run("factory", "stop")
        assert r.returncode == 0 and f"factory stopped (pid {pid})" in r.stdout, r.stdout
        st = status(s)
        assert st["state"] == "stopped" and s.w.run("factory", "status").stdout.startswith(
            "factory stopped")
        r = s.w.run("factory", "start")                       # red: the kill switch is set
        assert r.returncode == 2 and "kill switch is set" in r.stderr
        assert s.w.run("factory", "resume").returncode == 0
        r = s.w.run("factory", "start")                                      # green
        assert r.returncode == 0, r.stderr
        assert s.w.run("factory", "stop").returncode == 0
    finally:
        s.w.run("factory", "stop", "--now")
        s.w.stop_board()


@needs_jail
def test_kill_switch_drains_a_running_factory_and_refuses_a_start_red_green(tmp_path):
    s = make_lws(tmp_path)
    p = start_bg(s, "greeter")
    try:
        hb = wait_for(lambda: any(x["kind"] == "attempt" for x in heartbeat(s).get("steps", []))
                      and heartbeat(s), timeout=300, every=0.1)
        assert hb, f"{heartbeat(s)}\n{diagnose(s)}"
        r = s.w.run("factory", "stop", "--wait", "0")
        assert r.returncode == 0
        p.wait(timeout=300)
        assert p.returncode == 0                                    # a drain, not a crash
        assert heartbeat(s)["state"] == "stopped"
        rows = jobs(s)
        assert rows[0]["status"] == "verified" and s.ships() == []   # finished, nothing new
        r = factory(s, "run", "greeter", "--until-idle")                     # red
        assert r.returncode == 2 and "kill switch is set" in r.stderr
        assert s.w.run("factory", "resume").returncode == 0
        r = factory(s, "run", "greeter", "--until-idle")                     # green
        assert r.returncode == 0, r.stderr[-3000:]
        assert [x["state"] for x in s.ships()] == ["shipped", "shipped"]
    finally:
        kill_group(p)
        s.w.stop_board()


@needs_jail
def test_killed_factory_resumes_from_the_board_and_D6_view(tmp_path):
    s = make_lws(tmp_path)
    p = start_bg(s, "greeter")
    try:
        assert wait_for(lambda: any(x["kind"] == "attempt" and x["job"] == 3
                                    for x in heartbeat(s).get("steps", [])), timeout=300,
                        every=0.1), f"{heartbeat(s)}\n{diagnose(s)}"
        kill_group(p)                                     # the host dies: loop and steps
        assert status(s)["state"] == "stopped"
        r = factory(s, "run", "greeter", "--until-idle")
        assert r.returncode == 0, r.stderr[-3000:]
        assert [x["state"] for x in s.ships()] == ["shipped", "shipped"]
        assert notify_lines(s) == []
        view = s.w.json("factory", "status")
        assert view["goals"] == [{"goal": "greeter", "status": "done", "intake": "filed"}]
        # D6: the read route of the view with the viewer token
        viewer = s.w.home / "var" / "secrets" / "viewer.token"
        req = urllib.request.Request(f"http://127.0.0.1:{port(s)}/api/factory/goals/greeter",
                                     headers={"Authorization": "Bearer "
                                              + viewer.read_text().strip()})
        raw = urllib.request.urlopen(req, timeout=10).read().decode()
        g = json.loads(raw)
        assert {"budget", "jobs", "ships", "escalations"} <= set(g)
        assert [j["attempts"] for j in g["jobs"]] == [1, 2]        # the killed attempt counted
        assert all(j["attempts_left"] == j["max_attempts"] - j["attempts"] for j in g["jobs"])
        assert g["budget"]["max_task_runs"]["used"] == 3
        for needle in ("RUN:", "EXPECT", "khc-", "SCENARIO:"):
            assert needle not in raw
    finally:
        kill_group(p)
        s.w.stop_board()


def port(s) -> int:
    from konstant import config
    return config.load(config_path=str(s.w.home / "konstant.toml")).data["board"]["port"]


@needs_jail
def test_stall_without_progress_is_escalated_red(tmp_path):
    s = make_lws(tmp_path, factory="stall_after_s = 3")
    p = start_bg(s, "greeter", STUB_DSH_ACTIONS="sleep:20")     # every phase hangs, silent
    try:
        line = wait_for(lambda: [x for x in notify_lines(s) if "factory stalled" in x],
                        timeout=120)
        assert line and line[0].startswith("BLOCKED -: factory stalled: no progress for"), line
        time.sleep(4)                                             # told once, not every tick
        assert len([x for x in notify_lines(s) if "stalled" in x]) == 1
    finally:
        kill_group(p)
        time.sleep(1)
        s.w.stop_board()


@needs_jail
def test_no_stall_while_the_factory_makes_progress_green(tmp_path):
    s = make_lws(tmp_path, factory="stall_after_s = 30")
    try:
        r = factory(s, "run", "greeter", "--until-idle")
        assert r.returncode == 0, r.stderr[-3000:]
        assert not [x for x in notify_lines(s) if "stalled" in x]
    finally:
        s.w.stop_board()


def test_hung_loop_heartbeat_goes_stale_in_status_and_doctor(tmp_path):
    s = make_lws(tmp_path, goal=False)
    try:
        assert s.w.run("factory", "start").returncode == 0
        pid = status(s)["factory"]["pid"]
        doc = s.w.run("doctor", "--json")
        row = [r for r in json.loads(doc.stdout)["checks"] if r["check"] == "factory"]
        assert row and row[0]["status"] == "PASS", row
        os.kill(pid, signal.SIGSTOP)                               # hung: no more ticks
        time.sleep(4)
        assert status(s)["state"] == "stale"
        doc = s.w.run("doctor", "--json")
        row = [r for r in json.loads(doc.stdout)["checks"] if r["check"] == "factory"]
        assert row[0]["status"] == "WARN" and "no heartbeat" in row[0]["detail"], row
        os.kill(pid, signal.SIGCONT)
    finally:
        s.w.run("factory", "stop", "--now")
        s.w.stop_board()


def test_install_unit_writes_but_never_enables(tmp_path):
    s = make_lws(tmp_path, goal=False)
    try:
        r = s.w.run("factory", "install-unit", "--json")
        assert r.returncode == 0, r.stderr
        res = json.loads(r.stdout)
        assert res["enabled"] is False
        path = s.w.home / "var" / "factory" / "systemd"
        unit = next(path.glob("konstant-factory-*.service")).read_text()
        home = os.path.realpath(s.w.home)
        for line in (f"ExecStart={home}/bin/konstant factory run", "KillMode=mixed",
                     "Restart=on-failure", "RestartPreventExitStatus=2 4",
                     f"WorkingDirectory={home}"):
            assert line in unit
        assert res["unit"] == unit
    finally:
        s.w.stop_board()


def test_factory_verbs_refused_inside_a_task_run_red(tmp_path):
    s = make_lws(tmp_path, goal=False)
    try:
        for verb in ("run", "start", "stop", "resume"):
            r = s.w.run("factory", verb, env=s.w.env(KONSTANT_IN_TASK="1"))
            assert r.returncode == 2 and "inside a task run" in r.stderr, (verb, r.stderr)
        r = s.w.run("factory", "run", "--until-idle", env=s.w.env(KONSTANT_CHAT_SESSION="s1"))
        assert r.returncode == 2 and "orchestrator chat" in r.stderr
        assert s.w.run("factory", "status").returncode == 0                  # green: reading
    finally:
        s.w.stop_board()

