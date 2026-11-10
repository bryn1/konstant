"""The project's own test: the default greeting. konstant runs it after every ship (the
post-ship `tests` check), so a change that breaks it is rolled back."""
from greeter import greet


def test_default_greeting():
    assert greet() == "hello world"
