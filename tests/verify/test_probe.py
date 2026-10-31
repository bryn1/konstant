"""probe.py: line extraction, the five row outcomes, expected refusals, native shapes."""
from __future__ import annotations

import hashlib
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from konstant.verify import probe


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        self.send_response(404 if self.path == "/gone" else 200)
        self.end_headers()
        self.wfile.write(b'{"status": "up"}')

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def run(line, roots, **kw):
    return probe.run_line(line, roots, **kw)


def test_probe_lines_bullets_tags_and_dedupe_green():
    text = ("DoD: x\n- PROBE: test -e a => ^ok$\n  * PROBE:   test -e a => ^ok$\n> PROBE: ls -ld b => d\n"
            "PROBE-REFUSED: cat x => ^ok$ => allowlisted\nnot a PROBE: line\n")
    assert probe.probe_lines(text) == [
        "PROBE: test -e a => ^ok$", "PROBE: ls -ld b => d",
        "PROBE-REFUSED: cat x => ^ok$ => allowlisted"]
    assert probe.probe_lines(None) == []


def test_regex_may_hold_alternation_and_anchors_green(roots):
    row = run("PROBE: grep -c one f.txt => ^(2|3)$", roots)
    assert row["error"] is None and row["expect"] == "^(2|3)$" and row["matched"] is True


def test_line_splits_on_the_last_separator_red(roots):
    row = run("PROBE: grep -c one f.txt => ^2$ => ^2$", roots)     # command part = "... => ^2$"
    assert row["error"].startswith("refused") and row["expect"] is None


def test_matched_row_green(roots):
    row = run("PROBE: test -e f.txt => ^ok$", roots)
    assert row["matched"] is True and row["error"] is None and row["rc"] == 0
    assert row["output"] == "ok\n" and row["kind"] == "probe" and row["source"] == "dod"
    assert probe.verdict_of(row) == "matched"


def test_contradiction_row_red(roots):
    row = run("PROBE: test -e missing.txt => ^ok$", roots, source="closer")
    assert row["matched"] is False and row["error"] is None and row["output"] == "absent\n"
    assert row["source"] == "closer" and probe.verdict_of(row) == "contradiction"


def test_test_e_never_echoes_the_path_red(roots, home):
    (home / "d" / "ok-i-do-not-exist").mkdir(exist_ok=True)
    row = run("PROBE: test -e ok-i-do-not-exist => ^ok$", roots)
    assert row["matched"] is False and row["output"] == "absent\n"


def test_refused_row_is_unverifiable_red(roots):
    row = run("PROBE: cat /etc/passwd => root", roots)
    assert row["error"].startswith("refused:") and row["matched"] is False and row["rc"] is None
    assert probe.verdict_of(row) == "unverifiable"


def test_timeout_row_via_runner_red(roots):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired("ls", 1)
    row = run("PROBE: ls -ld f.txt => f.txt", roots, timeout=1, runner=slow)
    assert row["error"] == "timeout after 1s" and probe.verdict_of(row) == "unverifiable"


def test_timeout_row_native_curl_red(roots):
    with socket.socket() as s:                    # accepts connections, never answers
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        row = run(f"PROBE: curl -s http://127.0.0.1:{s.getsockname()[1]}/ => up", roots, timeout=0.5)
    assert row["error"] == "timeout after 0.5s"


def test_output_is_capped_green(roots, home):
    (home / "big.txt").write_text("line\n" * 40000)
    row = run("PROBE: stat -c %s big.txt => ^200000$", roots)
    assert row["matched"] is True
    big = run("PROBE: grep -c line big.txt => ^40000$", roots)
    assert big["matched"] is True and len(big["output"]) <= probe.OUTPUT_CAP


def test_grep_stat_ls_sha_green(roots, home):
    assert run("PROBE: grep -c one f.txt => ^2$", roots)["matched"]
    assert run("PROBE: stat -c %s f.txt => ^12$", roots)["matched"]
    assert run("PROBE: ls -ld f.txt => -rw.* .*f.txt$", roots)["matched"]
    digest = hashlib.sha256((home / "f.txt").read_bytes()).hexdigest()
    assert run(f"PROBE: sha256sum f.txt => ^{digest}", roots)["matched"]
    assert not run("PROBE: grep -c absent-word f.txt => ^1$", roots)["matched"]


def test_sqlite_native_rows_pipe_joined_green(roots):
    row = run('PROBE: sqlite3 -readonly data.db "SELECT a, b FROM t ORDER BY a" => ^2\\|$', roots)
    assert row["matched"] is True and row["output"] == "1|x\n2|\n"


def test_sqlite_cannot_write_red(roots):
    row = run('PROBE: sqlite3 -readonly data.db "SELECT 1; DELETE FROM t" => x', roots)
    assert row["error"].startswith("refused")                 # `;` never reaches sqlite
    bad = run('PROBE: sqlite3 -readonly data.db "SELECT load_extension(1)" => rows', roots)
    assert bad["matched"] is False


def test_sqlite_select_over_attach_is_denied_red(roots, home):
    row = run('PROBE: sqlite3 -readonly data.db "SELECT * FROM missing" => no such table', roots)
    assert row["matched"] is True and row["rc"] == 1


def test_curl_native_green(roots, server):
    assert run(f"PROBE: curl -s {server}/ => \"status\": \"up\"", roots)["matched"]
    row = run(f"PROBE: curl -s -o /dev/null -w %{{http_code}} {server}/gone => ^404$", roots)
    assert row["matched"] is True and row["output"] == "404"


def test_curl_does_not_follow_redirects_red(roots, server):
    row = run(f"PROBE: curl -s -o /dev/null -w %{{http_code}} {server}/moved => ^302$", roots)
    assert row["matched"] is True


def test_curl_host_outside_url_hosts_refused_red(roots):
    assert run("PROBE: curl -s http://example.com/ => up", roots)["error"].startswith("refused")


def test_git_shapes_run_green(roots, home):
    head = subprocess.run(["git", "-C", str(home / "repo"), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert run(f"PROBE: git -C repo rev-parse HEAD => ^{head}$", roots)["matched"]
    assert run("PROBE: git -C repo log -1 --format=%ae HEAD => ^t@example.com$", roots)["matched"]
    assert run("PROBE: git -C repo log -1 --format=%s HEAD => ^c1$", roots)["matched"]
    # REVIEW F-04: `status --porcelain` would run a repo's clean filter; it is refused
    assert run("PROBE: git -C repo status --porcelain => \\?\\? new.txt", roots)["error"]


def test_blob_sha256_native_green(roots, home):
    head = subprocess.run(["git", "-C", str(home / "repo"), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    digest = hashlib.sha256(b"committed\n").hexdigest()
    row = run(f"PROBE: git -C repo blob-sha256 HEAD:f.txt => ^sha256: {digest}  {head}:f.txt$", roots)
    assert row["matched"] is True
    (home / "repo" / "f.txt").write_text("edited after commit\n")       # the working file moved on
    assert run(f"PROBE: git -C repo blob-sha256 HEAD:f.txt => ^sha256: {digest}", roots)["matched"]


def test_blob_sha256_missing_path_is_unverifiable_red(roots):
    row = run("PROBE: git -C repo blob-sha256 HEAD:nope.txt => ^sha256: [0-9a-f]{64}", roots)
    assert row["matched"] is False and row["error"]


def test_git_env_is_pinned_green(roots, home, monkeypatch):
    seen = {}

    def fake(argv, **kw):
        seen.update(kw["env"])
        return subprocess.CompletedProcess(argv, 0, "abc\n", "")
    monkeypatch.setenv("KONSTANT_HOME", "/nope")
    monkeypatch.setenv("MY_SECRET_THING", "s")
    run("PROBE: git -C repo rev-parse HEAD => ^abc$", roots, runner=fake)
    assert seen["GIT_TERMINAL_PROMPT"] == "0" and "core.fsmonitor=false" in seen["GIT_CONFIG_PARAMETERS"]
    assert "credential.helper=" in seen["GIT_CONFIG_PARAMETERS"]
    assert "gpg.program=/bin/false" in seen["GIT_CONFIG_PARAMETERS"]
    assert "core.askpass=/bin/false" in seen["GIT_CONFIG_PARAMETERS"]
    assert "KONSTANT_HOME" not in seen and "MY_SECRET_THING" not in seen


def test_git_log_gets_no_show_signature_green(roots):
    seen = {}

    def fake(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "xy\n", "")
    row = run("PROBE: git -C repo log -1 --format=%H HEAD => ^xy$", roots, runner=fake)
    assert "--no-show-signature" in seen["argv"] and row["argv"][-1] == "HEAD"
    assert "--no-show-signature" not in row["argv"]


# ---- PROBE-REFUSED ----

def test_expected_refusal_refused_inner_is_matched_green(roots):
    row = run("PROBE-REFUSED: cat /etc/passwd => root => not an allowlisted", roots)
    assert row["kind"] == "expected-refusal" and row["refused"] is True
    assert row["matched"] is True and row["error"] is None
    assert row["output"].startswith("refused: not an allowlisted")


def test_expected_refusal_accepted_inner_is_contradiction_red(roots):
    row = run("PROBE-REFUSED: test -e f.txt => ^ok$ => allowlist", roots)
    assert row["refused"] is False and row["matched"] is False and row["error"] is None
    assert "ACCEPTS" in row["output"] and probe.verdict_of(row) == "contradiction"


def test_expected_refusal_never_runs_the_inner_line_red(roots, home):
    marker = home / "marker"
    row = run(f"PROBE-REFUSED: test -e {marker} => ^ok$ => nope", roots,
              runner=lambda *a, **k: pytest.fail("ran"))
    assert row["refused"] is False and not marker.exists()


def test_expected_refusal_malformed_and_trivial_reason_are_errors_red(roots):
    assert run("PROBE-REFUSED: cat x => root", roots)["error"].startswith("refused: an expected refusal")
    assert "trivial reason" in run("PROBE-REFUSED: cat x => root => .*", roots)["error"]
    assert "not a regex" in run("PROBE-REFUSED: cat x => root => (", roots)["error"]


def test_expected_refusal_metacharacter_reason_green(roots):
    row = run("PROBE-REFUSED: test -e f.txt; rm x => ^ok$ => control/shell character", roots)
    assert row["matched"] is True


def test_check_line_never_runs_and_judges_both_tags_green(roots, home):
    marker = home / "m"
    assert probe.check_line(f"PROBE: test -e {marker} => ^ok$", roots) is None
    assert "ACCEPTS" in probe.check_line("PROBE-REFUSED: test -e f.txt => ^ok$ => refused", roots)
    assert probe.check_line("PROBE-REFUSED: cat x => ^ok$ => allowlisted", roots) is None
    assert "not an allowlisted" in probe.check_line("PROBE: cat x => root", roots)
    assert "no '=>'" in probe.check_line("PROBE: test -e f.txt", roots)
