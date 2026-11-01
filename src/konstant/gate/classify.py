"""Deterministic task classifier (DESIGN §6.2). No model; vocabulary from catalog/types.yaml.

Order: an explicit `[type:x]` tag wins (an unknown tag is reported and the words decide; a
flag-only type such as `intake` counts as unknown: it is reachable only with `--type`);
else a question (the FIRST small shape: a question-word opener ending in `?`) that is not a
request ("can you / could you / would you ...?" asks for work) -> small; else the first type
(catalog order, `code` last) whose keywords match, when the task also carries a deliverable
signal or is long (>= 400 chars) -> `keyword:<word>`; a bare imperative naming a target ("review
the parser", "add retries to the client") -> `imperative:<word>`; only THEN the other small shapes
(a message that is only a chat opener, a read-only opener like "show"/"list") -> small; no
deliverable signal -> small (`no-deliverable`); else `code` (`deliverable-signal`). Keywords come
before the chat/read-only openers so an opener never ungates the work that follows it (REVIEW
F-16).
"""
from __future__ import annotations

import re

TAG = re.compile(r"\[type:([a-z_-]+)\]", re.I)
LONG = 400
REQUEST = re.compile(r"^\s*(?:please\s+)?(?:can|could|would|will)\s+(?:you|we)\b", re.I)


def _word(m) -> str:
    groups = [g for g in m.groups() if g] if m.groups() else []
    return (groups[0] if groups else m.group(0)).strip().lower()


def keyword_hit(text: str, cat):
    low = text.lower()
    for t in cat.classifiable():                 # a flag-only type (intake) is never picked
        m = re.search(cat.keywords(t), low)
        if m:
            return t, _word(m)
    return None, None


def classify(task: str, cat) -> tuple:
    """(type or None, why). None = small: run inline, no gate."""
    m = TAG.search(task)
    if m:
        tag = m.group(1).lower()
        if tag in cat.classifiable():
            return tag, "tag"
        t, _w = keyword_hit(TAG.sub(" ", task), cat)
        return (t or "code"), f"unknown-tag:{tag}"
    low = task.lower()
    shapes = cat.small_shapes()
    short = len(task) < LONG and not REQUEST.search(low)
    if short and any(re.search(sh, low, re.S) for sh in shapes[:1]):
        return None, "small-shape"
    t, word = keyword_hit(task, cat)
    deliverable = re.search(cat.deliverable_signal(), low) is not None
    if t and (deliverable or len(task) >= LONG):
        return t, f"keyword:{word}"
    if t and re.search(cat.imperative(), low) and not task.strip().endswith("?"):
        return t, f"imperative:{word}"
    if short and any(re.search(sh, low, re.S) for sh in shapes[1:]):
        return None, "small-shape"
    if not deliverable:
        return None, "no-deliverable"
    return "code", "deliverable-signal"
