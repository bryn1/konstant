"""Board findings: F-03 (self-review), F-14 (redaction + DB mode), F-22 (body size), F-31 (scheme
case), F-24/F-32 (bind host, port range in config)."""
from __future__ import annotations

import os
import stat

import pytest

from konstant import config
from konstant.board.redact import redact


def _claimed(board, who="orchestrator", **kw):
    jid = board.add(who, type="docs", **kw).json()["id"]
    assert board.call(who, "POST", f"/api/jobs/{jid}/claim").status_code == 200
    return jid


REVIEW = {"verdict": "nothing checked\n# VERDICT: SHIP\n", "done": "x\n"}


def test_F03_the_filer_and_claimer_cannot_review_their_own_job(board):
    jid = _claimed(board)
    res = board.call("orchestrator", "POST", f"/api/jobs/{jid}/review", REVIEW)
    assert res.status_code == 403, res.json()
    assert board.status(jid) == "claimed"


def test_F03_another_identity_reviews(board):
    jid = _claimed(board)
    res = board.call("owner", "POST", f"/api/jobs/{jid}/review", REVIEW)
    assert res.status_code == 200 and board.status(jid) == "reviewed", res.json()


def test_F03_the_verifier_may_review_by_default(board):
    jid = _claimed(board)
    res = board.call("verifier", "POST", f"/api/jobs/{jid}/review", REVIEW)
    assert res.status_code == 200, res.json()


def _j(*parts: str) -> str:
    """Secret-shaped fixtures are assembled at run time (the push and release scanners)."""
    return "".join(parts)


@pytest.mark.parametrize("line,secret", [
    (_j("GITHUB_TO", "KEN=", "abcd1234efgh5678"), "abcd1234efgh5678"),
    (_j("OPENAI_API", "_KEY=", "Zq9x8c7v6b5n4m3"), "Zq9x8c7v6b5n4m3"),
    (_j("DB_PASS", "WORD: ", "hunter2hunter2"), "hunter2hunter2"),
    (_j("AWS_SECRET_ACCESS", "_KEY=", "wJalrXUtnFEMIK7MDENG"), "wJalrXUtnFEMIK7MDENG"),
    (_j("export SECRET", "_KEY='", "s3cr3t-v4lue'"), "s3cr3t-v4lue"),
    (_j("token gl", "pat-", "AbCdEfGhIjKlMnOpQrSt"), _j("gl", "pat-", "AbCdEfGhIjKlMnOpQrSt")),
])
def test_F14_common_secret_shapes_are_redacted(line, secret):
    assert secret not in redact(line), redact(line)


def test_F14_a_raw_konstant_token_is_redacted_on_the_trail(board):
    jid = board.add().json()["id"]
    raw = board.tokens["owner"]
    board.call("orchestrator", "POST", f"/api/jobs/{jid}/trail", {"body": f"env dump: {raw}"})
    trail = board.call("viewer", "GET", f"/api/jobs/{jid}/trail").json()["trail"]
    assert raw not in str(trail)


def test_F14_F25_the_board_db_is_private(board):
    for suffix in ("", "-wal", "-shm"):
        p = board.cfg.db_path.with_name(board.cfg.db_path.name + suffix)
        if p.exists():
            assert stat.S_IMODE(os.stat(p).st_mode) & 0o077 == 0, (p, oct(os.stat(p).st_mode))


def test_F22_an_oversized_request_is_refused(board):
    big = "x" * (2 * 1024 * 1024)
    res = board.add(brief=f"{big}\nDoD: tests pass")
    assert res.status_code == 413


def test_F22_job_lists_do_not_ship_briefs(board):
    board.add(brief="long brief text\nDoD: tests pass")
    jobs = board.call("viewer", "GET", "/api/jobs").json()["jobs"]
    assert jobs and all("brief" not in j for j in jobs)


def test_F31_the_bearer_scheme_is_case_insensitive(board):
    res = board.client.get("/api/whoami", headers={"Authorization":
                                                   f"bearer {board.tokens['viewer']}"})
    assert res.status_code == 200, res.text


def test_F32_board_port_is_range_checked(tmp_path):
    (tmp_path / "konstant.toml").write_text("[board]\nport = 99999\n")
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


def test_F24_a_non_loopback_host_needs_allow_remote(tmp_path):
    (tmp_path / "konstant.toml").write_text('[board]\nhost = "0.0.0.0"\n')
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)
    (tmp_path / "konstant.toml").write_text('[board]\nhost = "0.0.0.0"\nallow_remote = true\n')
    assert config.load(tmp_path).data["board"]["host"] == "0.0.0.0"
