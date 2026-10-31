"""The classifier (DESIGN §6.2): deterministic, two-sided fixtures; every type's keywords hit."""
from __future__ import annotations

import pytest

from konstant import catalog
from konstant.gate.classify import classify

CAT = catalog.load()


@pytest.mark.parametrize("task,want", [
    ("what is the board?", (None, "small-shape")),
    ("how do I add a project?", (None, "small-shape")),
    ("thanks", (None, "small-shape")),
    ("show me the open jobs", (None, "small-shape")),
    ("Implement a rate limiter; DoD: tests pass?", ("code", "keyword:implement")),
    ("Implement the token-bucket rate limiter; DoD: tests pass, review PASS?", ("code", "keyword:implement")),
    ("[type:docs] write the user guide", ("docs", "tag")),
    ("[type:poetry] write a module for greetings", ("code", "unknown-tag:poetry")),
    ("[type:poetry] harden the login file handling", ("security", "unknown-tag:poetry")),
    ("review the parser", ("review", "imperative:review")),
    ("is the review of the parser done?", (None, "small-shape")),
    ("the weather is nice", (None, "no-deliverable")),
    ("the tests are flaky in ci", ("code", "deliverable-signal")),
])
def test_classify_fixtures(task, want):
    assert classify(task, CAT) == want


@pytest.mark.parametrize("ttype,task", [
    ("security", "harden the upload module; deliver a report"),
    ("review", "audit the payment module and deliver a report"),
    ("docs", "write the README for the cli; save to docs/README.md"),
    ("infra", "deploy the board behind nginx with a systemd unit; DoD: the file exists"),
    ("frontend", "build the landing page component in react; deliver index.html file"),
    ("research", "compare three queue libraries; deliver a report"),
    ("design", "write a design doc for the data model; deliver docs/design.md"),
    ("test", "write a pytest suite for greet.py"),
    ("code", "fix the bug in parser.py"),
])
def test_every_type_is_reachable_by_keywords(ttype, task):
    t, why = classify(task, CAT)
    assert t == ttype and why.startswith("keyword:"), (t, why)


def test_a_question_mark_alone_is_not_small():
    t, why = classify("Refactor the module greet.py so tests pass?", CAT)
    assert t == "code" and why == "keyword:refactor"


def test_long_text_with_a_keyword_is_typed():
    t, why = classify("please refactor " + "the thing " * 50, CAT)
    assert t == "code" and why == "keyword:refactor"
