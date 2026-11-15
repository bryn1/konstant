"""The fixed routing corpus of the orchestrator chat (REVIEW L5-R2 K-09): plain owner-style
messages, the way a person who does not know konstant's keywords writes them, each with the route
the owner expects. `goal` = work: it changes files in a project, has a deliverable or needs more
than one short answer, so konstant proposes it as a goal. `inline` = one short answer in the chat.
The first 13 are the reviewer's own probes (REVIEW-L5-R2 K-09), with the route it called correct;
the rest were written before the router's rules and are never edited to fit them. The project of
the sample workspace is `greeter`.
"""
from __future__ import annotations

PROJECTS = ["greeter"]

CORPUS = [
    # the reviewer's probes
    ("one small job in greeter: greet(name) returns hello <name>", "goal"),
    ("greeter should greet people by name", "goal"),
    ("can you add a --shout flag to greeter", "goal"),
    ("please fix the bug where greet crashes on an empty name", "goal"),
    ("the README of greeter needs a usage section", "goal"),
    ("implement greet(name) in greeter", "goal"),
    ("make greeter faster", "goal"),
    ('greet(name) should return "hello <name>" in greeter', "goal"),
    ("I want greeter to say hello to whoever calls it", "goal"),
    ("rename greet to welcome in greeter", "goal"),
    ("delete the projects folder", "goal"),
    ("what does greet do?", "inline"),
    ("should we add a CLI to greeter? just tell me how you would do it", "inline"),
    # work, phrased plainly
    ("add a goodbye function next to greet", "goal"),
    ("greeter needs tests", "goal"),
    ("could you write a small changelog for greeter", "goal"),
    ("let's give greeter a --version flag", "goal"),
    ("greet prints the wrong thing when the name has spaces", "goal"),
    ("I'd like greeter to support Swedish greetings too", "goal"),
    ("it would be nice if greeter could greet a list of names", "goal"),
    ("move the greeting text into a config file", "goal"),
    ("greeter: the --help output is missing the examples", "goal"),
    ("put a license file in greeter", "goal"),
    ("clean up the greeter code, it is messy", "goal"),
    ("we need a docs page that explains how to install greeter", "goal"),
    ("update the README so it matches the new flags", "goal"),
    ("greeter crashes on python 3.10", "goal"),
    ("can we have greeter print the time of day as well?", "goal"),
    ("support a --name option in greeter please", "goal"),
    ("bump the version of greeter to 0.2", "goal"),
    ("greet() returns None for an empty string, it should raise ValueError", "goal"),
    ("write tests for the CLI of greeter and make them pass", "goal"),
    ("greeter has no error handling yet", "goal"),
    ("set up a small benchmark for greeter", "goal"),
    ("translate the greeter messages to german", "goal"),
    ("make the greeting configurable through an environment variable", "goal"),
    # one short answer
    ("hi", "inline"),
    ("thanks!", "inline"),
    ("good morning", "inline"),
    ("what is the status of my goals?", "inline"),
    ("how is it going?", "inline"),
    ("show me the open escalations", "inline"),
    ("list the projects", "inline"),
    ("explain how the ship step works", "inline"),
    ("why did job 1.2 fail?", "inline"),
    ("is greeter broken?", "inline"),
    ("which python version does greeter need?", "inline"),
    ("can you explain what a holdout is?", "inline"),
    ("could you tell me what the factory is doing right now", "inline"),
    ("summarize the README of greeter", "inline"),
    ("how do I add a new project?", "inline"),
    ("does greeter have tests?", "inline"),
    ("what changed in the last ship?", "inline"),
    ("add a goodbye function to greeter - no, just answer: how long would that take?", "inline"),
    ("just answer: what would you change in greeter first?", "inline"),
    ("ok", "inline"),
    ("tell me a short joke", "inline"),
    ("remind me what max_attempts means", "inline"),
    ("where are the logs of the factory?", "inline"),
    ("when did the last goal finish?", "inline"),
]
