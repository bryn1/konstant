"""The notifier (docs/LEVEL5.md 6.3, 4.0 step 3; wave L5-5).

  D4  `notify test --kind webhook` against a local server: JSON with event and reason, without
      brief, acceptance or evidence keys
  D5  a webhook that refuses every request, during a run: exit 4 `notifier failed: factory
      halted`, the event in var/factory/spool/; the next start refused until `factory resume`
  chat  the escalation is posted into the orchestrator session the goal came from and shows up in
      that session's next turn (a `konstant dsh` session on the stub dsh; its `run:` action
      stands in for the konstant-gate plugin's `chat turn`)
  dedupe  one notification per (goal, job, event) until `factory ack`
Each refusal has a _red and a _green test."""
from __future__ import annotations

import http.server
import json
import os
import sys
import threading

import pytest

from konstant.factory import notify
from tests.factory.loopkit import events, factory, make_lws, notify_lines
from tests.holdout.conftest import needs_jail


class Hook:
    """A local webhook receiver: records every POST; `refuse` answers 503."""

    def __init__(self, refuse: bool = False):
        self.got, self.refuse = [], refuse
        hook = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                hook.got.append(json.loads(self.rfile.read(n)))
                self.send_response(503 if hook.refuse else 204)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/hook"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def webhook_conf(url: str) -> str:
    return f'kind = "webhook"\nurl = "{url}"\nurl_hosts = ["127.0.0.1"]\nretries = 1\nretry_s = 0'


def test_webhook_url_rules_red_green():
    assert notify.check_url("https://hooks.example.org/x", []) is None            # green
    assert notify.check_url("http://127.0.0.1:9/x", ["127.0.0.1"]) is None         # green
    for bad, hosts in (("http://127.0.0.1:9/x", []), ("http://example.org/x", ["example.org"]),
                       ("ftp://127.0.0.1/x", ["127.0.0.1"]), ("", [])):
        assert notify.check_url(bad, hosts), bad                                    # red


def test_D4_notify_test_webhook_payload_has_no_content_keys(tmp_path):
    hook = Hook()
    s = make_lws(tmp_path, notify=webhook_conf(hook.url), goal=False)
    try:
        r = s.w.run("notify", "test", "--kind", "webhook")
        assert r.returncode == 0 and "delivered to webhook 127.0.0.1" in r.stdout, r.stderr
        assert len(hook.got) == 1
        body = hook.got[0]
        assert body["event"] == "TEST" and body["reason"]
        assert set(body) == set(notify.PAYLOAD)
        assert not {"brief", "acceptance", "evidence"} & set(body)
    finally:
        hook.close()
        s.w.stop_board()


def test_D4_notify_test_refusing_webhook_fails_red(tmp_path):
    hook = Hook(refuse=True)
    s = make_lws(tmp_path, notify=webhook_conf(hook.url), goal=False)
    try:
        r = s.w.run("notify", "test")
        assert r.returncode == 1 and "did not take the event after 2 tries (HTTP 503)" in r.stderr
        assert len(hook.got) == 2                                    # 1 + [notify] retries
    finally:
        hook.close()
        s.w.stop_board()


@needs_jail
def test_D5_notifier_failure_halts_the_factory_red(tmp_path):
    hook = Hook(refuse=True)
    s = make_lws(tmp_path, notify=webhook_conf(hook.url), limits="max_attempts = 1")
    try:
        r = factory(s, "run", "greeter", "--until-idle", mode="tester-fails-3x")
        assert r.returncode == 4, r.stderr[-3000:]
        assert "notifier failed: factory halted" in r.stderr
        spool = list((s.w.home / "var" / "factory" / "spool").glob("*.json"))
        assert len(spool) == 1
        rec = json.loads(spool[0].read_text())
        assert rec["event"] == "BLOCKED" and "HTTP 503" in rec["undelivered"]
        assert any(x.startswith("HALTED") for x in notify_lines(s))      # stderr + file at least
        assert s.w.json("factory", "status")["halted"] is True
        # no dark factory: it does not start again while the owner cannot be reached
        r = factory(s, "run", "greeter", "--until-idle")
        assert r.returncode == 2 and "halted" in r.stderr, r.stderr
        r = s.w.run("factory", "resume")                        # still refusing: stays halted
        assert r.returncode == 4 and "still halted" in r.stderr
        hook.refuse = False
        r = s.w.run("--as", "owner", "factory", "resume")
        assert r.returncode == 0, r.stderr
        assert hook.got[-1]["event"] == "BLOCKED" and not list(
            (s.w.home / "var" / "factory" / "spool").glob("*.json"))
        assert s.w.json("factory", "status")["halted"] is False
    finally:
        hook.close()
        s.w.stop_board()


@needs_jail
def test_D5_delivering_webhook_keeps_the_factory_running_green(tmp_path):
    hook = Hook()
    s = make_lws(tmp_path, notify=webhook_conf(hook.url), limits="max_attempts = 1")
    try:
        r = factory(s, "run", "greeter", "--until-idle", mode="tester-fails-3x")
        assert r.returncode == 4 and "notifier failed" not in r.stderr, r.stderr[-3000:]
        assert [b["event"] for b in hook.got] == ["BLOCKED"]
        assert not list((s.w.home / "var" / "factory" / "spool").glob("*.json"))
        assert s.w.json("factory", "status")["halted"] is False
    finally:
        hook.close()
        s.w.stop_board()


def emit(s, event="BLOCKED", job=None, reason="r"):
    code = ("from konstant import config; from konstant.factory import notify; "
            f"print(notify.emit(config.load(), {event!r}, 'greeter', {job!r}, '', {reason!r}))")
    return s.w.run_py(code) if hasattr(s.w, "run_py") else __import__("subprocess").run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=s.w.env(),
        cwd=str(s.w.home))


def test_one_notification_per_goal_job_event_until_ack_red_green(tmp_path):
    s = make_lws(tmp_path)
    try:
        for _ in range(3):
            assert emit(s).returncode == 0
        assert len(notify_lines(s)) == 1                                       # red: deduped
        assert [e.get("suppressed") for e in events(s)] == [None, True, True]
        assert emit(s, "DECISION").returncode == 0                      # another event: told
        assert len(notify_lines(s)) == 2
        esc = s.w.json("factory", "escalations", "--open")
        r = s.w.run("--as", "orchestrator", "factory", "ack", str(esc[0]["id"]))   # refused
        assert r.returncode == 1 and "only the owner" in r.stderr
        r = s.w.run("--as", "owner", "factory", "ack", str(esc[0]["id"]))
        assert r.returncode == 0, r.stderr
        assert emit(s).returncode == 0                                  # green: told again
        assert len(notify_lines(s)) == 3
    finally:
        s.w.stop_board()


@needs_jail
def test_chat_escalation_reaches_the_session_the_goal_came_from(tmp_path):
    """[notify] kind = chat: the goal is proposed in session S and confirmed by the owner's yes;
    the factory's BLOCKED is posted into S's inbox, and the session's next turn shows it. A
    goal-less second session sees nothing of it."""
    from tests.fixtures import stub_dsh  # noqa: F401 - installed on PATH by make_ws
    s = make_lws(tmp_path, notify='kind = "chat"', goal=False)
    try:
        cfg = s.w.home / "konstant.toml"
        s.w.stop_board()
        cfg.write_text(cfg.read_text().replace(
            "[factory]\n", '[factory]\ngoal_roles = ["owner", "orchestrator"]\n', 1))
        s.w.ok("board", "start")
        s.w.ok("agents", "sync")
        spec = (tmp_path / "src" / "chatgoal.toml")
        from tests.factory.loopkit import goal_text
        spec.write_text(goal_text("max_attempts = 1"))
        r = s.w.run("goal", "add", spec, "--from-chat", "--session", "sess-a")
        assert r.returncode == 0, r.stderr
        t = s.w.run("chat", "turn", "--session", "sess-a", "yes")
        assert t.returncode == 0 and json.loads(t.stdout)["confirmed"] == "greeter", t.stderr
        r = factory(s, "run", "greeter", "--until-idle", mode="tester-fails-3x")
        assert r.returncode == 4, r.stderr[-3000:]
        inbox = notify.read_inbox(s.w.home, "sess-a")
        assert [e["event"] for e in inbox] == ["BLOCKED"]
        log = tmp_path / "dsh.log"
        k = f"{sys.executable} -m konstant chat turn --session"
        env = s.w.env(PATH=f"{s.w.bindir}:{os.environ['PATH']}", STUB_DSH_LOG=str(log),
                      STUB_DSH_ACTIONS=f"run:{k} sess-a how is it going;"
                                       f"run:{k} sess-b anything for me")
        res = s.w.run("dsh", "web", env=env)
        assert res.returncode == 0, res.stderr
        acts = {r["act"]: r for r in map(json.loads, log.read_text().splitlines()) if "act" in r}
        a = json.loads(acts[f"run:{k} sess-a how is it going"]["out"])
        assert any(x.startswith("konstant BLOCKED: goal greeter job 1.1:") for x in a["lines"])
        b = json.loads(acts[f"run:{k} sess-b anything for me"]["out"])
        assert not any("BLOCKED" in x for x in b["lines"])
    finally:
        s.w.stop_board()


def test_chat_delivery_to_a_bad_session_spools_red(tmp_path):
    s = make_lws(tmp_path, notify='kind = "chat"', goal=False)
    try:
        from konstant import config
        cfg = config.load(config_path=str(s.w.home / "konstant.toml"))
        with pytest.raises(notify.NotifyError):
            notify.deliver(cfg, {"id": 1, "event": "BLOCKED", "session": "../escape",
                                 "reason": "x"})
        assert notify.deliver(cfg, {"id": 2, "event": "BLOCKED", "session": "ok-1",
                                    "reason": "x"}) == "chat ok-1"
    finally:
        s.w.stop_board()
