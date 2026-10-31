"""Secrets never land in the board: redaction before insert."""
from __future__ import annotations

import pytest

from konstant.board.redact import REDACTED, redact, redact_obj


def _j(*parts: str) -> str:
    """Secret-SHAPED fixtures are assembled at run time so no literal secret shape sits in the
    source (the repository's own push scanner and the release scan would rightly refuse it)."""
    return "".join(parts)


SECRETS = [
    _j("Authorization: Bear", "er abcdefghijklmnop1234"),
    _j("key s", "k-abcdefghijklmnop"),
    _j("slack xo", "xb-1234567890-abcdef"),
    _j("gh token gh", "p_", "a" * 36),
    _j("aws AK", "IA", "A" * 16),
    _j("api_k", "ey=supersecretvalue"),
    _j("pass", "word: hunter2hunter2"),
    _j("postgres://user:pa55word", "@db.example.com/x"),
    _j("-----BEGIN RSA PRIV", "ATE KEY-----\nMIIabc\n-----END RSA PRIV", "ATE KEY-----"),
]


@pytest.mark.parametrize("text", SECRETS)
def test_secret_shapes_are_redacted(text):
    out = redact(text)
    assert REDACTED in out and out != text


@pytest.mark.parametrize("text", ["12 passed in 0.3s", "token budget is fine", "see api docs",
                                  "commit abc123def456"])
def test_ordinary_text_is_untouched(text):
    assert redact(text) == text


def test_lone_surrogates_and_nesting():
    assert redact("x\udc94y") == "x\ufffdy"
    assert redact_obj({"a": [_j("pass", "word=abcdefgh")], "n": 3}) == \
        {"a": [_j("pass", "word=") + REDACTED], "n": 3}
    assert redact(None) is None


def test_secrets_in_a_brief_and_a_note_never_reach_the_db(board):
    job = board.add(brief=_j("Use api_k", "ey=topsecret99 here.\nDoD: done")).json()
    board.call("worker", "POST", f"/api/jobs/{job['id']}/trail",
               {"body": _j("tok", "en: abcdefghij123")})
    raw = board.cfg.db_path.read_bytes()
    wal = board.cfg.db_path.with_name(board.cfg.db_path.name + "-wal")
    raw += wal.read_bytes() if wal.exists() else b""
    assert b"topsecret99" not in raw and b"abcdefghij123" not in raw
    assert REDACTED in board.call("viewer", "GET", f"/api/jobs/{job['id']}").json()["brief"]
