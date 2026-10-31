"""Rule `exercise` (Python only): the tests under OUT enter at least one function of every
non-test `.py` file under OUT that defines a function. The rule-`tests` pytest run IS the traced
run: a generated sitecustomize.py (first on PYTHONPATH, chaining to any it shadows) records every
function entry under OUT (call events only, stdlib sys.settrace). Applied when the record asks
for it (build types) and OUT holds tests."""
from __future__ import annotations

import ast
import json
import os
import shutil
import tempfile

from konstant.gate.rules.common import CACHE_DIRS, RUN_DIRS

SITECUSTOMIZE = r'''
import atexit, json, os, sys, threading
_OUT = os.environ.get("KONSTANT_EXERCISE_OUT"); _REC = os.environ.get("KONSTANT_EXERCISE_REC")
if _OUT and _REC:
    _seen = set()
    def _trace(frame, event, arg):
        if event == "call" and frame.f_code.co_filename.startswith(_OUT):
            _seen.add((os.path.realpath(frame.f_code.co_filename), frame.f_code.co_name))
        return None
    sys.settrace(_trace); threading.settrace(_trace)
    @atexit.register
    def _dump():
        try:
            with open(_REC, "a") as fh:
                fh.write("".join(json.dumps([p, n]) + "\n" for p, n in _seen))
        except OSError:
            pass
try:
    import importlib.machinery, importlib.util
    _here = os.path.dirname(os.path.realpath(__file__))
    _spec = importlib.machinery.PathFinder.find_spec(
        "sitecustomize", [p for p in sys.path if os.path.realpath(p or ".") != _here])
    if _spec and _spec.origin and os.path.realpath(_spec.origin) != os.path.realpath(__file__):
        _mod = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_mod)
except Exception:
    pass
'''


def source_functions(out: str) -> dict:
    found = {}
    for root, dirs, files in os.walk(out):
        dirs[:] = [d for d in dirs if d not in CACHE_DIRS and d not in RUN_DIRS]
        for fn in files:
            if (not fn.endswith(".py") or fn.startswith("test_") or fn.endswith("_test.py")
                    or fn == "conftest.py"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, out)
            if any(p in ("test", "tests") for p in rel.split(os.sep)[:-1]):
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except (OSError, SyntaxError, ValueError):
                continue
            names = {n.name for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if names:
                found[rel] = names
    return found


def traced_env(out: str):
    tmp = tempfile.mkdtemp(prefix="konstant-exercise-")
    with open(os.path.join(tmp, "sitecustomize.py"), "w") as fh:
        fh.write(SITECUSTOMIZE)
    rec = os.path.join(tmp, "entered.jsonl")
    pp = os.environ.get("PYTHONPATH")
    env = {"KONSTANT_EXERCISE_OUT": os.path.realpath(out) + os.sep, "KONSTANT_EXERCISE_REC": rec,
           "PYTHONPATH": tmp + (os.pathsep + pp if pp else "")}
    return env, tmp, rec


def unexercised(out: str, rec: str) -> list:
    real = os.path.realpath(out)
    entered = set()
    try:
        with open(rec) as fh:
            for line in fh:
                try:
                    p, n = json.loads(line)
                    entered.add((os.path.relpath(p, real), n))
                except (ValueError, TypeError):
                    pass
    except OSError:
        pass
    return [f"{rel} (functions: {', '.join(sorted(names)[:6])})"
            for rel, names in sorted(source_functions(real).items())
            if not any((rel, n) in entered for n in names)]


def cleanup(tmp: str) -> None:
    shutil.rmtree(tmp, ignore_errors=True)
