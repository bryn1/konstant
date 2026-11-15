"""REVIEW L5-R2 (wave L5-F2b), the owner's seat: K-05, K-08, K-09, K-13, K-16 - each reviewer
reproduction as a must-fail test (red on 53ac137), with "should stay allowed" twins.

K-05: the chat notifier delivers what has no session (a file goal, `notify test`); doctor proves
      the route end to end;
K-08: every `konstant dsh` session hears an escalation, a new one too; delivery is the turn;
K-16: an escalation that lands while a turn runs is shown at the next turn, never skipped;
K-09: routing decides on the owner's words (a fixed corpus, >= 90%); only an explicit yes files;
K-13: the generated units bring the board and the factory back; a down board is waited out and
      told through the second channel."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from tests.fixtures.route_corpus import CORPUS, PROJECTS
from tests.holdout.conftest import make_ws, needs_jail

S = "sess-a"


def chat_ws(tmp_path, extra: str = ""):
    w = make_ws(tmp_path)
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[factory]\ngoal_roles = ["owner", "orchestrator"]\n'
                    '[notify]\nkind = "chat"\n' + extra)
    w.ok("board", "stop")
    w.ok("board", "start")
    return w


def turn(w, text: str, session: str = S) -> dict:
    r = w.run("chat", "turn", "--session", session, "-", stdin=text)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def propose(w, gid: str = "greeter", text: str = "greet by name", session: str = S):
    spec = f'[goal]\nid = "{gid}"\nproject = "greeter"\ntext = "{text}"\n[limits]\n' \
           'max_attempts = 3\n'
    return w.run("--as", "orchestrator", "goal", "add", "-", "--from-chat", "--session",
                 session, stdin=spec)


def cfg_of(w):
    from konstant import config
    return config.load(w.home)


def esc_rows(w) -> list:
    return w.json("factory", "escalations")


# --- K-05 -------------------------------------------------------------------------------------

@needs_jail
def test_K05_notify_test_under_chat_reaches_the_next_turn(tmp_path):
    w = chat_ws(tmp_path)
    try:
        turn(w, "hi")                                    # the session exists (a cursor)
        r = w.run("notify", "test")
        assert r.returncode == 0, r.stderr
        lines = turn(w, "anything new?")["lines"]
        assert any(ln.startswith("konstant TEST:") for ln in lines), lines
        assert not any("TEST" in ln for ln in turn(w, "and now?")["lines"])   # shown once
        doc = w.run("doctor").stdout
        assert any(ln.startswith("PASS") and "notifier" in ln for ln in doc.splitlines()), doc
    finally:
        w.stop_board()


@needs_jail
def test_K05_a_file_goal_escalation_reaches_the_chat(tmp_path):
    from konstant.factory import notify
    w = chat_ws(tmp_path)
    try:
        turn(w, "hi")
        rec = notify.emit(cfg_of(w), "BLOCKED", "", None, "", "holdout authoring refused")
        assert not rec.get("undelivered"), rec
        assert not notify.spooled(w.home)
        lines = turn(w, "status?")["lines"]
        assert any(ln.startswith("konstant BLOCKED: goal -") for ln in lines), lines
    finally:
        w.stop_board()


def test_K05_one_session_id_scheme_checked_at_write_and_read(tmp_path):
    from konstant.factory import chat, notify
    for bad in ("../escape", "", "a/b", "-x"):
        with pytest.raises(ValueError):
            notify.session_id(bad)
        with pytest.raises(ValueError):
            chat.cursor_path(tmp_path, bad)
    assert notify.session_id("web:2026-11-15.a_b") == "web:2026-11-15.a_b"


# --- K-08 + K-16 ------------------------------------------------------------------------------

@needs_jail
def test_K08_every_session_hears_it_and_the_turn_is_the_delivery(tmp_path):
    from konstant.factory import notify
    w = chat_ws(tmp_path)
    try:
        assert propose(w).returncode == 0
        assert turn(w, "yes")["confirmed"] == "greeter"
        rec = notify.emit(cfg_of(w), "BLOCKED", "greeter", None, "", "holdout authoring refused")
        e = next(x for x in esc_rows(w) if x["id"] == rec["escalation"])
        assert e["delivered_at"] is None, e              # an append is not a delivery
        b = turn(w, "good morning, anything for me?", session="sess-b")["lines"]
        assert any(ln.startswith("konstant BLOCKED: goal greeter") for ln in b), b
        e = next(x for x in esc_rows(w) if x["id"] == rec["escalation"])
        assert e["delivered_at"] and e["delivered_to"] == "chat session sess-b", e
        a = turn(w, "and?")["lines"]
        assert any(ln.startswith("konstant BLOCKED: goal greeter") and "filed in this chat" in ln
                   for ln in a), a
        assert not any("BLOCKED" in ln for ln in turn(w, "more?", session="sess-b")["lines"])
    finally:
        w.stop_board()


@needs_jail
def test_K08_twin_a_new_session_does_not_replay_acknowledged_ones(tmp_path):
    from konstant.factory import notify
    w = chat_ws(tmp_path)
    try:
        rec = notify.emit(cfg_of(w), "BLOCKED", "", None, "", "old news")
        w.ok("--as", "owner", "factory", "ack", rec["escalation"])
        assert not any("old news" in ln for ln in turn(w, "hi", session="sess-new")["lines"])
    finally:
        w.stop_board()


@needs_jail
def test_K16_an_escalation_landing_mid_turn_is_shown_next_turn(tmp_path, monkeypatch):
    from konstant.client import Client, token_for
    from konstant.factory import chat, notify
    w = chat_ws(tmp_path)
    try:
        monkeypatch.setenv("KONSTANT_HOME", str(w.home))
        cfg = cfg_of(w)
        client = Client(cfg.base_url, token_for(cfg, "orchestrator"))
        chat.turn(cfg, client, S, "hi")
        real = notify.read_events
        fired = []

        def late(home):                       # the notifier writes while the turn reads
            if not fired:
                fired.append(None)
                monkeypatch.setattr(notify, "read_events", real)
                fired[0] = notify.emit(cfg, "BLOCKED", "", None, "", "arrived mid-turn")
            return real(home)
        monkeypatch.setattr(notify, "read_events", late)
        chat.turn(cfg, client, S, "status?")
        monkeypatch.setattr(notify, "read_events", real)
        lines = chat.turn(cfg, client, S, "anything else?")["lines"] + \
            chat.turn(cfg, client, S, "and now?")["lines"]
        assert fired and not fired[0].get("undelivered"), fired
        assert sum("arrived mid-turn" in ln for ln in lines) == 1, lines   # shown, once
    finally:
        w.stop_board()


# --- K-09 -------------------------------------------------------------------------------------

def _routes(tmp_path) -> list:
    """(text, expected, routed-as-goal?) per corpus message, through `chat turn` itself."""
    from konstant.client import Client, token_for
    from konstant.factory import chat
    w = chat_ws(tmp_path)
    try:
        cfg = cfg_of(w)
        os.environ["KONSTANT_HOME"] = str(w.home)
        client = Client(cfg.base_url, token_for(cfg, "orchestrator"))
        return [(t, exp, chat.turn(cfg, client, f"corpus-{i}", t)["intake"])
                for i, (t, exp) in enumerate(CORPUS)]
    finally:
        os.environ.pop("KONSTANT_HOME", None)
        w.stop_board()


@needs_jail
def test_K09_plain_requests_route_by_konstants_rule_90_percent(tmp_path):
    assert len(CORPUS) >= 40 and {e for _t, e in CORPUS} == {"goal", "inline"}
    assert PROJECTS == ["greeter"]
    rows = _routes(tmp_path)
    right = [t for t, exp, intake in rows if intake == (exp == "goal")]
    wrong = [(t, exp) for t, exp, intake in rows if intake != (exp == "goal")]
    assert len(right) / len(rows) >= 0.90, wrong
    assert not [t for t, exp, intake in rows if exp == "inline" and intake and
                "just answer" in t], "the owner's 'just answer' must keep it inline"


@needs_jail
@pytest.mark.parametrize("reply", ["ok", "sure", "do it", "okay", "yep"])
def test_K09_a_vague_reply_never_files_a_goal(tmp_path, reply):
    w = chat_ws(tmp_path)
    try:
        assert propose(w).returncode == 0
        t = turn(w, reply)
        assert t["confirmed"] is None and t["withdrawn"] == "greeter", t
    finally:
        w.stop_board()


@needs_jail
@pytest.mark.parametrize("reply", ["yes", "ja", "go", "Yes."])
def test_K09_twin_an_explicit_yes_files_it_and_echoes_what(tmp_path, reply):
    w = chat_ws(tmp_path)
    try:
        assert propose(w, text="greet people by name").returncode == 0
        t = turn(w, reply)
        assert t["confirmed"] == "greeter", t
        filed = [ln for ln in t["lines"] if "FILED" in ln]
        assert filed and '"greet people by name"' in filed[0], t["lines"]
    finally:
        w.stop_board()


# --- K-13 -------------------------------------------------------------------------------------

@needs_jail
def test_K13_units_bring_the_board_and_the_factory_back(tmp_path):
    w = make_ws(tmp_path)
    try:
        r = w.run("factory", "install-unit")
        assert r.returncode == 0, r.stderr
        d = w.home / "var" / "factory" / "systemd"
        board = [p for p in d.iterdir() if p.name.startswith("konstant-board-")]
        fac = [p for p in d.iterdir() if p.name.startswith("konstant-factory-")]
        assert board and fac, sorted(p.name for p in d.iterdir())
        text = fac[0].read_text()
        assert f"Wants={board[0].name}" in text and board[0].name in \
            next(ln for ln in text.splitlines() if ln.startswith("After="))
        prevent = [ln for ln in text.splitlines() if ln.startswith("RestartPreventExitStatus")]
        assert prevent == ["RestartPreventExitStatus=4"], prevent        # exit 2 restarts
        assert "Restart=on-failure" in text and "RestartMaxDelaySec=" in text
        assert "board serve" in board[0].read_text()
        assert "enable --now" in r.stdout
        doc = w.run("doctor").stdout
        assert any(ln.startswith("PASS") and " units " in f" {ln} " for ln in doc.splitlines()), doc
        fac[0].write_text(text.replace("RestartSec=30", "RestartSec=1"))
        doc = w.run("doctor").stdout
        assert any(ln.startswith("WARN") and "units" in ln for ln in doc.splitlines()), doc
    finally:
        w.stop_board()


@needs_jail
def test_K13_a_down_board_is_waited_out_and_told_through_the_mirror(tmp_path):
    w = make_ws(tmp_path)
    try:
        toml = w.home / "konstant.toml"
        toml.write_text(toml.read_text() + '[factory]\ntick_s = 1\ndown_after_s = 10\n'
                        '[notify]\nkind = "stdout"\nmirror = "file"\n')
        w.ok("board", "stop")
        p = subprocess.Popen([sys.executable, "-m", "konstant", "factory", "run"],
                             env=w.henv(), cwd=str(w.home), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            log = w.home / "var" / "factory" / "notify.log"
            end = time.time() + 60
            while time.time() < end and not (log.is_file() and "factory down" in
                                             log.read_text()):
                assert p.poll() is None, p.communicate()[1][-2000:]   # never exits 2
                time.sleep(0.5)
            assert log.is_file() and "factory down" in log.read_text()
            assert p.poll() is None
            w.ok("board", "start")
            end = time.time() + 60
            while time.time() < end and not (w.home / "var" / "factory" / "factory.pid").exists():
                time.sleep(0.5)
            hb = w.home / "var" / "factory" / "heartbeat.json"
            end = time.time() + 60
            while time.time() < end and not (hb.is_file() and
                                             json.loads(hb.read_text())["state"] == "running"):
                time.sleep(0.5)
            assert json.loads(hb.read_text())["state"] == "running"
        finally:
            os.killpg(p.pid, signal.SIGTERM)
            p.communicate(timeout=60)
    finally:
        w.stop_board()


def test_K13_twin_until_idle_still_refuses_a_down_board(tmp_path):
    w = make_ws(tmp_path)
    try:
        w.ok("board", "stop")
        r = w.run("factory", "run", "--until-idle", env=w.henv())
        assert r.returncode == 2 and "refused" in r.stderr, r.stderr
    finally:
        w.stop_board()
