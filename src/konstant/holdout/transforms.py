"""Common obfuscations of a held-out literal, for the leak scan and the memory store-time scan
(REVIEW L5-R1 H-09).

The verbatim scans (holdout/leak.py, memory/guard.py) match a literal's exact bytes. A producer
that learned a held-out value can hide it: change its case, split it across string pieces or lines
(`"A" + "da"`), reverse it, or encode it (base64, hex, percent-encoding). `appears(needle,
haystack)` catches those without a model:

- an ALPHANUMERIC-ONLY, lower-cased fold of both sides catches case changes, whitespace and line
  splits, and splits across quotes/operators (`"A"+"da"` folds to `...ada...`);
- the reversed fold catches a reversed literal;
- base64 / hex / percent-encoding of the needle's bytes are searched in the raw haystack.

STATED LIMIT (docs/CONCEPTS.md "Security model and limits"): this is a fixed list, not a decoder.
A custom cipher, compression, a per-character arithmetic transform, or a value split across
SEPARATE notes/files so no single text holds it, still passes. Read prevention (H-03, H-04: the
store and the memory pools are unreadable to producers) is the primary control; this scan is the
backstop for a literal that reached a producer through a hole not yet found.
"""
from __future__ import annotations

import base64
import re
import urllib.parse

_ALNUM = re.compile(r"[^a-z0-9]+")
MIN_LEN = 4


def fold(text: str) -> str:
    """Lower-case, keep only [a-z0-9]: collapses case, whitespace, line breaks and the
    punctuation a split hides behind (`"A" + "da"` -> `ada`)."""
    return _ALNUM.sub("", (text or "").lower())


def encoded_forms(needle: str) -> list:
    """base64 (standard and url-safe, with and without padding), hex, and percent-encoding of the
    needle's UTF-8 bytes - the forms a stored value is most often hidden as."""
    raw = (needle or "").encode("utf-8", "replace")
    if not raw:
        return []
    forms = {
        base64.b64encode(raw).decode(),
        base64.b64encode(raw).decode().rstrip("="),
        base64.urlsafe_b64encode(raw).decode(),
        base64.urlsafe_b64encode(raw).decode().rstrip("="),
        raw.hex(),
        urllib.parse.quote(needle, safe=""),
    }
    return [f for f in forms if len(f) >= MIN_LEN]


def appears(needle: str, haystack: str) -> bool:
    """Whether `needle` appears in `haystack` verbatim or under a common transform."""
    if not needle or len(needle) < MIN_LEN:
        return False
    if needle in haystack:
        return True
    nf, hf = fold(needle), fold(haystack)
    if len(nf) >= MIN_LEN and (nf in hf or nf[::-1] in hf):
        return True
    low = haystack.lower()
    return any(form.lower() in low for form in encoded_forms(needle))
