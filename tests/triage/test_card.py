"""The intake card (konstant/triage/card.py): computed by code before planning, through a real board
(`board start`) and the real CLI: new vs continuation, prior work (memory, verified first), reuse
candidates, research required when nothing is found, recorded on the job, injected into every
phase prompt. Each rule red-then-green."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from tests.cli.conftest import Workspace

REPO = Path(__file__).resolve().parents[2]
FAKE = f"{sys.executable} {REPO / 'tests' / 'fixtures' / 'fake_harness.py'} {{prompt_file}}"
BRIEF = "Add a greeting.\n\nDoD:\n- greet() returns hello\nPROBE: test -f {p}/greet.py => ^ok$\n"


@pytest.fixture()
def ws(tmp_path):
    w = Workspace(tmp_path)
    w.ok("board", "init")
    w.ok("board", "start")
    try:
        w.ok("project", "add", "demo")
        proj = tmp_path / "projects" / "demo"
        for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "i"]):
            subprocess.run(["git", "-C", str(proj), "-c", "user.email=t@example.com", "-c",
                            "user.name=t", *args], check=True)
        yield w
    finally:
        w.stop_board()


def gate(w, task, *extra):
    return json.loads(w.ok("--json", "task", "gate", task, "--project", "demo", *extra).stdout)


def add_job(w, title, brief=None):
    f = w.write("brief.md", brief or BRIEF.format(p=w.home / "projects" / "demo"))
    return json.loads(w.ok("--json", "job", "add", title, "--project", "demo", "--type", "code",
                           "--brief", f).stdout)


def set_status(w, jid, status):
    with sqlite3.connect(w.home / "var" / "board.db") as conn:
        conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, jid))


def test_new_task_with_nothing_found_requires_research_and_says_so(ws):
    g = gate(ws, "[type:code] add a pelican renderer to the zork module")
    card = g["card"]
    assert card["continuation"] == "new" and card["related"] == [] and card["prior_work"] == []
    assert card["research_required"] is True and "nothing similar" in card["research_why"]
    assert "=== INTAKE CARD" in g["block"] and "task research" in g["block"]
    rec = json.loads((Path(g["run_dir"]) / "record.json").read_text())
    assert rec["card"]["sha256"] == card["sha256"]


def test_similar_closed_job_is_prior_work_and_no_research_red_green(ws):
    task = "[type:code] add a pelican renderer to the zork module"
    assert gate(ws, task)["card"]["research_required"] is True                  # red
    j = add_job(ws, "pelican renderer for zork")
    set_status(ws, j["id"], "verified")
    card = gate(ws, task)["card"]                                               # green
    assert card["continuation"] == "new" and card["research_required"] is False
    assert [r["id"] for r in card["related"]] == [j["id"]]
    assert card["related"][0]["status"] == "verified" and "pelican" in card["related"][0]["matched"]


def test_an_open_job_on_the_same_keywords_makes_it_a_continuation(ws):
    j = add_job(ws, "pelican renderer for zork")
    card = gate(ws, "[type:code] add a pelican renderer to the zork module")["card"]
    assert card["continuation"] == "continuation" and j["display_id"] in card["continuation_why"]
    assert card["research_required"] is False


def port_of(w) -> int:
    return int((w.home / "konstant.toml").read_text().split("port = ")[1].split()[0])


def call(w, label, method, path, body=None):
    tok = (w.home / "var" / "secrets" / f"{label}.token").read_text().strip()
    req = urllib.request.Request(f"http://127.0.0.1:{port_of(w)}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {tok}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def test_memory_prior_work_is_recalled_verified_lessons_first(ws):
    ws.ok("memory", "store", "pelican rendering in zork needs the quill library")
    j = add_job(ws, "some other job about lighthouses")
    run = ws.home / "var" / "runs" / "r-lesson"           # a run of job j wrote the lesson
    run.mkdir(parents=True)
    (run / "record.json").write_text(json.dumps({"job": j["id"]}))
    st, _b = call(ws, "worker", "POST", "/api/memory/store",
                  {"text": "zork pelican sprites are drawn bottom up", "run": "r-lesson"})
    assert st == 200
    card = gate(ws, "[type:code] add a pelican renderer to the zork module")["card"]
    assert len(card["prior_work"]) == 2 and card["research_required"] is False
    assert card["prior_work"][0]["verified"] is False                 # red: job not verified yet
    set_status(ws, j["id"], "verified")
    card = gate(ws, "[type:code] add a pelican renderer to the zork module")["card"]
    assert card["prior_work"][0]["verified"] is True and "sprites" in card["prior_work"][0]["title"]
    assert "PRIOR WORK" in gate(ws, "[type:code] add a pelican renderer to zork")["block"]


def test_reuse_candidates_name_existing_files_and_skills(ws):
    proj = ws.home / "projects" / "demo"
    (proj / "renderer.py").write_text("x = 1\n")
    card = gate(ws, "[type:code] add a pelican mode to renderer.py with a security review")["card"]
    kinds = {(r["kind"], r.get("path") or r.get("name")) for r in card["reuse"]}
    assert ("file", "renderer.py") in kinds
    assert any(k == "skill" for k, _n in kinds)


def test_a_bound_job_is_a_continuation_and_the_card_is_recorded_on_it(ws):
    j = add_job(ws, "greet by name")
    g = gate(ws, "[type:code] add greet()", "--job", str(j["id"]))
    assert g["card"]["continuation"] == "continuation" and "bound to job" in \
        g["card"]["continuation_why"]
    show = json.loads(ws.ok("--json", "job", "show", str(j["id"]), "--trail").stdout)
    cards = show["intake_cards"]
    assert len(cards) == 1 and cards[0]["card"]["sha256"] == cards[0]["sha256"]
    assert cards[0]["tier"] == "agent" and cards[0]["actor"] == "orchestrator"
    assert any(t["body"].startswith("intake card: [type:code] tier agent") for t in show["trail"])


def test_a_phase_token_cannot_record_a_card_red_and_orchestrator_can_green(ws):
    j = add_job(ws, "greet by name")
    card = gate(ws, "[type:code] add greet()")["card"]
    path = f"/api/jobs/{j['id']}/intake-card"
    assert call(ws, "worker", "POST", path, {"card": card})[0] == 403               # red
    assert call(ws, "researcher", "POST", path, {"card": card})[0] == 403
    assert call(ws, "orchestrator", "POST", path, {"card": card})[0] == 200        # green
    bad = {**card, "tier": {"name": "unbounded"}}
    assert call(ws, "orchestrator", "POST", path, {"card": bad})[0] == 422


def test_the_card_reaches_every_phase_prompt_but_not_the_closeout(ws):
    j = add_job(ws, "greet by name")
    res = ws.run("task", "run", "[type:code] add greet()", "--job", str(j["id"]), "--harness",
                 FAKE, "--max-resumes", "0")
    runs = sorted((ws.home / "var" / "runs").iterdir())
    prompts = sorted((runs[-1] / "prompts").glob("*.md"))
    assert prompts, res.stderr
    for p in prompts:
        text = p.read_text()
        if "-0-orchestrator-" in p.name:
            assert "=== INTAKE CARD" not in text
        else:
            assert "## Intake card" in text and "TIER: agent" in text, p.name
    assert "tier agent" in res.stderr
