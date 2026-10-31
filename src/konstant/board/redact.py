"""Secret redaction applied to every text field before it is stored (DESIGN §4.1).

A stdlib scrubber: PEM private keys, bearer headers, provider-prefixed keys, NAME=value secret
assignments whose NAME merely CONTAINS a secret word (GITHUB_TOKEN, DB_PASSWORD, OPENAI_API_KEY,
AWS_SECRET_ACCESS_KEY ...; REVIEW F-14), passwords embedded in URLs, and every value registered
with `register_secrets` (the board registers konstant's own role tokens at start and on rotate, so
a raw token pasted into a note is redacted although it has no recognisable shape). Lone UTF-16
surrogates are replaced first: one split multi-byte character stored as an escape made every
later render of the row fail.
"""
from __future__ import annotations

import re

REDACTED = "[REDACTED]"
_LONE_SURROGATES = re.compile("[\ud800-\udfff]")
_KNOWN: set = set()
_SECRET_NAME = (r"(?:token|secret|password|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|"
                r"client[_-]?secret|auth[_-]?key|credentials?)")


def register_secrets(values) -> None:
    """Exact values to redact wherever they appear (at least 16 characters, to stay specific)."""
    _KNOWN.update(v for v in values if isinstance(v, str) and len(v.strip()) >= 16)

# Order matters: more specific patterns first.
_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.DOTALL), REDACTED),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"), r"\1 " + REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), REDACTED),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}"), REDACTED),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), REDACTED),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}"), REDACTED),
    (re.compile(r"\bnpm_[A-Za-z0-9]{30,}"), REDACTED),
    (re.compile(r"\bpypi-[A-Za-z0-9_\-]{40,}"), REDACTED),
    (re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}"), REDACTED),
    (re.compile(r"(?i)(?<![A-Za-z0-9])([A-Za-z0-9_.-]*" + _SECRET_NAME + r"[A-Za-z0-9_]*)"
                r"(\s*[:=]\s*)([\"']?)([^\s\"'&]{4,})"),
     lambda m: f"{m.group(1)}{'=' if '=' in m.group(2) else m.group(2)}{m.group(3)}{REDACTED}"),
    (re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^\s:/@]+):[^\s:/@]+@"), r"\1:" + REDACTED + "@"),
]


def redact(text):
    """Scrub secrets from a string. Non-strings are returned unchanged."""
    if not isinstance(text, str) or not text:
        return text
    out = _LONE_SURROGATES.sub("\ufffd", text)
    for value in _KNOWN:
        if value in out:
            out = out.replace(value, REDACTED)
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_obj(obj):
    """Recursively redact strings inside dicts/lists (payload JSON)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj
