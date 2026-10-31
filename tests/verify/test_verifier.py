"""settle (pure), collect, and `konstant verify` end to end against a real board."""
from __future__ import annotations

import json

import pytest

from konstant.verify.verifier import collect, settle

M = {"error": None, "matched": True, "line": "PROBE: m", "output": "ok", "source": "dod"}
MC = {"error": None, "matched": True, "line": "PROBE: mc", "output": "ok", "source": "closer"}
C = {"error": None, "matched": False, "line": "PROBE: c", "output": "absent"}
U = {"error": "refused: nope", "matched": False, "line": "PROBE: u", "output": ""}
RR_OK = {"ran": True, "ok": True, "exit": 0, "timed_out": False}
RR_BAD = {"ran": True, "ok": False, "exit": 2, "cmd": "make", "timed_out": False}
RR_COMMIT = {"ran": False, "ok": False, "commit_ok": False, "skipped": "not an ancestor"}
RR_SKIP = {"ran": False, "ok": None, "skipped": "no directory"}
RR_TIMEOUT = {"ran": True, "ok": None, "timed_out": True, "cmd": "slow", "skipped": "timeout"}

TABLE = [
    ("PASS", [M], None), ("PASS", [M, M], RR_OK), ("PASS", [M], RR_SKIP), ("PASS", [M, MC], None),
    # REVIEW F-02: a re-run or the closer's own probes alone never settle PASS
    ("BLOCKED", [], RR_OK), ("BLOCKED", [MC], RR_OK), ("BLOCKED", [MC], None),
    ("FAIL", [M], RR_BAD), ("FAIL", [C], None), ("FAIL", [M, C], RR_OK), ("FAIL", [], RR_BAD),
    ("FAIL", [M], RR_COMMIT), ("FAIL", [U, C], None), ("FAIL", [U], RR_BAD),
    ("BLOCKED", [], None), ("BLOCKED", [], RR_SKIP), ("BLOCKED", [U], None),
    ("BLOCKED", [M, U], RR_OK), ("BLOCKED", [U], RR_OK), ("BLOCKED", [], RR_TIMEOUT),
    ("BLOCKED", [M], RR_TIMEOUT),
]


@pytest.mark.parametrize("want,rows,rerun", TABLE)
def test_settle_table(want, rows, rerun):
    verdict, reasons = settle(rows, rerun)
    assert verdict == want and reasons


def test_settle_pass_green_names_what_was_verified():
    assert "re-run exit 0" in settle([M], RR_OK)[1][0]
    assert "no re-run" in settle([M], None)[1][0]


def test_settle_fail_red_names_the_contradiction_and_the_rerun():
    reasons = settle([C], RR_BAD)[1]
    assert any("contradiction" in r and "PROBE: c" in r for r in reasons)
    assert any("re-run FAILED" in r and "exited 2" in r for r in reasons)


def test_collect_dod_first_closer_deduped_green():
    job = {"acceptance": "DoD: x\nPROBE: test -e a => ^ok$\n",
           "evidence": {"probes": ["PROBE: test -e a => ^ok$", "PROBE: ls -ld b => b",
                                   "PROBE-REFUSED: cat x => ^ok$ => allowlisted"]}}
    assert collect(job) == [("PROBE: test -e a => ^ok$", "dod"), ("PROBE: ls -ld b => b", "closer"),
                            ("PROBE-REFUSED: cat x => ^ok$ => allowlisted", "closer")]
    assert collect({"acceptance": "DoD: x", "evidence": None}) == []


# ---------------- end to end ----------------

GOOD = "VERIFY_CMD: test -f greet.py\ngreet.py present: 1 file checked\nVERIFY_EXIT=0\n"


def _file(ws, name="greet.py", present=True):
    p = ws.home / "projects" / "demo" / name
    if present:
        p.write_text("print('hi')\n")
    else:
        p.unlink(missing_ok=True)
    return p


def _job(ws, probe, evidence=GOOD, close_as=None):
    brief = f"Build greet.\n\nDoD: greet exists\n{probe}\n"
    out = ws.ok("job", "add", "T1: greet", "--project", "demo", "--type", "code",
                "--brief", ws.write("brief.md", brief)).stdout
    job = out.split()[0].split("=")[1]
    ws.ok("job", "claim", job)
    pre = ["--as", close_as] if close_as else []
    ws.ok(*pre, "job", "close", job, "--evidence", ws.write("ev.md", evidence))
    return job


def _verify(ws, job, *flags, env=None):
    res = ws.run("verify", job, "--json", *flags, env=env)
    return res, (json.loads(res.stdout) if res.stdout.strip().startswith(("{", "[")) else None)


def _status(ws, job):
    return json.loads(ws.ok("job", "show", job, "--json").stdout)["status"]


def test_w38_pass_then_fail_when_the_file_is_removed(ws):
    job = _job(ws, "PROBE: test -e projects/demo/greet.py => ^ok$")
    _file(ws)
    res, data = _verify(ws, job, "--dry-run")
    print(res.stdout)
    assert res.returncode == 0 and data["verdict"] == "PASS" and data["dry_run"] is True
    assert data["probes"][0]["matched"] is True and data["probes"][0]["source"] == "dod"
    assert data["rerun"]["exit"] == 0 and data["job"] == int(job)
    assert _status(ws, job) == "completed_unverified"          # dry-run wrote nothing
    _file(ws, present=False)
    res, data = _verify(ws, job, "--dry-run")
    print(res.stdout)
    assert res.returncode == 3 and data["verdict"] == "FAIL"
    assert data["probes"][0]["output"] == "absent\n" and data["rerun"]["exit"] == 1
    assert _status(ws, job) == "completed_unverified"


def test_w38_refused_probe_is_blocked(ws):
    _file(ws)
    job = _job(ws, "PROBE: cat /etc/passwd => root")
    res, data = _verify(ws, job, "--dry-run")
    print(res.stdout)
    assert res.returncode == 4 and data["verdict"] == "BLOCKED"
    assert data["probes"][0]["error"].startswith("refused:")
    assert data["rerun"]["exit"] == 0                  # the re-run passed; the probe is unverifiable


def test_pass_moves_the_job_to_verified_green(ws):
    _file(ws)
    job = _job(ws, "PROBE: test -e projects/demo/greet.py => ^ok$")
    res, data = _verify(ws, job)
    assert res.returncode == 0 and data["verdict"] == "PASS" and data["dry_run"] is False
    assert _status(ws, job) == "verified"
    trail = json.loads(ws.ok("job", "show", job, "--trail", "--json").stdout)["trail"]
    assert any(t["kind"] == "verdict" and "PASS" in t["body"] and t["actor"] == "verifier"
               for t in trail)


def test_fail_requeues_and_blocked_leaves_state_red(ws):
    _file(ws, present=False)
    job = _job(ws, "PROBE: test -e projects/demo/greet.py => ^ok$", evidence=GOOD.replace(
        "test -f greet.py", "test -d ."))
    res, data = _verify(ws, job)
    assert res.returncode == 3 and data["verdict"] == "FAIL"
    shown = json.loads(ws.ok("job", "show", job, "--trail", "--json").stdout)
    assert shown["status"] == "queued" and shown["verify_round"] == 1
    assert any(t["kind"] == "finding" and "contradiction" in t["body"] for t in shown["trail"])
    _file(ws)
    blocked = _job(ws, "PROBE: cat /etc/passwd => root")
    res, data = _verify(ws, blocked)
    assert res.returncode == 4 and _status(ws, blocked) == "completed_unverified"


def test_no_rerun_flag_and_nothing_to_verify_is_blocked_red(ws):
    _file(ws)
    job = _job(ws, "(no probes here)")
    res, data = _verify(ws, job, "--dry-run", "--no-rerun")
    assert res.returncode == 4 and data["rerun"] is None
    assert "nothing independent verified" in data["reasons"][0]
    res, data = _verify(ws, job, "--dry-run")          # REVIEW F-02: a re-run alone is not PASS
    assert res.returncode == 4 and data["verdict"] == "BLOCKED" and data["rerun"]["ok"] is True


def test_closer_probe_from_the_evidence_is_run_green(ws):
    _file(ws)
    ev = GOOD + "PROBE: test -e projects/demo/greet.py => ^ok$\n"
    job = _job(ws, "(no dod probe)", evidence=ev)
    res, data = _verify(ws, job, "--dry-run", "--no-rerun")
    assert [p["source"] for p in data["probes"]] == ["closer"] and data["probes"][0]["matched"]
    assert res.returncode == 4 and data["verdict"] == "BLOCKED"   # F-02: the closer's own probe


def test_wrong_state_and_unknown_job_exit_2_red(ws):
    out = ws.ok("job", "add", "T2: queued", "--project", "demo", "--type", "code", "--brief",
                ws.write("b.md", "x\n\nDoD: y\n")).stdout
    queued = out.split()[0].split("=")[1]
    res = ws.run("verify", queued, "--dry-run")
    assert res.returncode == 2 and "is queued, not completed_unverified" in res.stderr
    assert ws.run("verify", "99999", "--dry-run").returncode == 2
    assert ws.run("verify").returncode == 2


def test_closer_cannot_verify_own_job_red(ws):
    _file(ws)
    job = _job(ws, "PROBE: test -e projects/demo/greet.py => ^ok$", close_as="owner")
    res = ws.run("--as", "owner", "verify", job)
    assert res.returncode == 1 and "the closer cannot verify" in res.stderr
    assert _status(ws, job) == "completed_unverified"
    res, data = _verify(ws, job)                    # the verifier identity is another identity
    assert res.returncode == 0 and _status(ws, job) == "verified"


def test_in_task_run_may_dry_run_but_not_write_red(ws):
    _file(ws)
    job = _job(ws, "PROBE: test -e projects/demo/greet.py => ^ok$")
    env = ws.env(KONSTANT_IN_TASK="1")
    assert _verify(ws, job, "--dry-run", env=env)[0].returncode == 0
    res = ws.run("verify", job, env=env)
    assert res.returncode == 1 and "KONSTANT_IN_TASK=1" in res.stderr
    assert _status(ws, job) == "completed_unverified"


def test_pending_verifies_every_completed_unverified_job_green(ws):
    for j in json.loads(ws.ok("job", "list", "--status", "completed_unverified", "--json").stdout):
        ws.ok("--as", "verifier", "job", "verdict", j["display_id"], "BLOCKED", "cleanup")
        ws.ok("--as", "orchestrator", "job", "cancel", j["display_id"], "cleanup")
    _file(ws)
    a = _job(ws, "PROBE: test -e projects/demo/greet.py => ^ok$")
    b = _job(ws, "PROBE: test -e projects/demo/greet.py => ^ok$")
    res = ws.run("verify", "--pending", "--json")
    rows = json.loads(res.stdout)
    assert res.returncode == 0 and [r["verdict"] for r in rows] == ["PASS", "PASS"]
    assert _status(ws, a) == _status(ws, b) == "verified"
    assert ws.run("verify", "--pending").stdout.strip() == "no job awaits verification"
