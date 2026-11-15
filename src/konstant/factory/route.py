"""Routing in the orchestrator chat (REVIEW L5-R2 K-09; docs/LEVEL5.md 4.0): goal or inline.

Deterministic, no model, on the OWNER's message only (the model's phrasing never decides). The
owner talks plainly; a request that is not clearly inline-sized becomes a goal PROPOSAL by
default, and the owner keeps it inline by saying so ("just answer", "just tell me how", "no
goal", "don't build"). The tier rules, per sentence:

  work      an imperative that changes something ("add ...", "fix ...", "make greeter faster",
            "delete ..."); a request for one ("can you add ...", "could we have ..."); a wish or a
            need ("greeter should ...", "the README needs ...", "I'd like ...", "let's ...");
            a problem report that is not a question ("greet crashes on ...", "... is missing");
            a spec naming a known project and code ("in greeter: greet(name) returns ...");
            a work clause after "and/then/also" ("check it and fix it")
  inline    a question (a question word first, or a `?` at the end) that is not a request for
            work; an information request ("show", "list", "explain", "tell me", "summarize",
            "can you explain ..."); a greeting or an acknowledgement
A message is a goal when any sentence is work, or when it is long (>= 400 characters) and asks no
question; else inline. The owner's opt-out wins over everything. tests/fixtures/route_corpus.py is
the fixed corpus (plain owner-style messages of both kinds); the test requires >= 90% of it right.
"""
from __future__ import annotations

import re

LONG = 400
VERBS = (r"add|fix|make|implement|write|create|delete|remove|rename|update|change|refactor|"
         r"build|improve|support|port|rewrite|extract|move|replace|document|test|clean|set up|"
         r"setup|upgrade|migrate|speed up|convert|split|merge|publish|ship|deploy|release|bump|"
         r"translate|handle|allow|ensure|give|put|turn|drop|rework|redo|optimi[sz]e|simplify|"
         r"finish|complete|integrate|wire|hook up|enable|disable|install|configure|package|"
         r"polish|tidy|format|lint|correct|repair|introduce|expose|let|have|get")
INFO = (r"explain|tell|show|list|describe|summari[sz]e|remind|check|look|find out|say|walk me|"
        r"help me understand|give me|guess|estimate|compare|recommend|suggest|think")
OPT_OUT = re.compile(r"\b(just answer|just tell me (how|what|why|if|whether|which)|only answer|"
                     r"answer (it )?(inline|only|here)|no goal|without (a goal|filing)|"
                     r"do(n'?t| not) (build|file|make a goal|change anything|do it))\b", re.I)
SOCIAL = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|thx|ok|okay|cool|great|nice|bye|"
                    r"good (morning|evening|night|afternoon)|morning)\W*$", re.I)
QUESTION = re.compile(r"^\s*(what|what'?s|why|how|when|where|who|whose|which|is|are|was|were|"
                      r"does|do|did|has|have|had|should|shall|would|could|can|will|may|am)\b",
                      re.I)
REQUEST = re.compile(r"^\s*(?:please\s+)?(?:can|could|would|will)\s+(?:you|we|i)\s+(?:please\s+)?"
                     r"(\w+(?:\s+\w+)?)", re.I)
INFO_OPEN = re.compile(rf"^\s*(?:please\s+)?(?:{INFO})\b", re.I)
IMPERATIVE = re.compile(rf"^\s*(?:please\s+|ok,?\s+|so\s+|now\s+)?(?:{VERBS})\b", re.I)
CLAUSE = re.compile(rf"\b(?:and|then|also)\s+(?:please\s+)?(?:{VERBS})\b", re.I)
WISH = re.compile(r"\b(should|shall|needs?|must|has to|have to|ought to|want\w*\b.*\bto|"
                  r"would like|i'?d like|wish|would be nice|it'?d be nice|let'?s|we need)\b", re.I)
PROBLEM = re.compile(r"\b(bug|crash\w*|broken|fails?|failing|failed|errors?|wrong|missing|"
                     r"doesn'?t work|does not work|not working|too slow|is slow|has no|have no|"
                     r"lacks?|messy|outdated)\b", re.I)
CODE = re.compile(r"\w\(|--\w|\b\w+\.(py|md|sh|toml|ya?ml|json|txt|js|ts)\b|\bjob\b|\bfeature\b")
SPLIT = re.compile(r"(?<=[.?!;:])\s+|\n+|\s+-+\s+")


def sentences(text: str) -> list:
    return [s.strip() for s in SPLIT.split(text or "") if s and s.strip()]


def kind_of(sentence: str, projects=()) -> str:
    """work | question | info | social | neutral for one sentence."""
    s = sentence.strip()
    low = s.lower()
    if SOCIAL.match(s):
        return "social"
    m = REQUEST.match(s)
    if m:
        verb = m.group(1).lower()
        if re.match(rf"(?:{INFO})\b", verb) and not CLAUSE.search(s):
            return "info"
        return "work"
    if CLAUSE.search(s) and not s.endswith("?"):
        return "work"
    if QUESTION.match(s) or s.endswith("?"):
        return "question"
    if INFO_OPEN.match(s):
        return "info"
    if IMPERATIVE.match(s) or WISH.search(s) or PROBLEM.search(s):
        return "work"
    named = any(re.search(rf"\b{re.escape(p.lower())}\b", low) for p in projects if p)
    if named and CODE.search(s):
        return "work"
    return "neutral"


def route(text: str, projects=()) -> tuple:
    """("goal" | "inline", why) for one owner message."""
    t = (text or "").strip()
    if not t:
        return "inline", "empty"
    if OPT_OUT.search(t):
        return "inline", "owner-said-inline"
    kinds = [kind_of(s, projects) for s in sentences(t)]
    if "work" in kinds:
        return "goal", "work:" + next(s for s, k in zip(sentences(t), kinds) if k == "work")[:60]
    if len(t) >= LONG and "question" not in kinds:
        return "goal", "long"
    return "inline", "+".join(dict.fromkeys(kinds)) or "neutral"
