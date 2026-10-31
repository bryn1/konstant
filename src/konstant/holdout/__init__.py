"""Sealed holdout scenarios (docs/LEVEL5.md 3): black-box acceptance checks for one job, written
before the producer claims it, stored where no producing phase can read them (var/holdout/,
machinery.SEALED), and run only by the verifier (verify/holdout.py).

  lint.py   the scenario file format: parse, the lint rules, the expectation match
  store.py  seal (lint + negative control + commitment on the board), list, check, show
  leak.py   canary and literal scans the verifier runs before any scenario
"""
