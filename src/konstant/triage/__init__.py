"""Triage (docs/CONCEPTS.md "Triage"): what the orchestrator decides about a task before any model
plans it, all by code.

- `tiers.py`: the size tier on top of the type classifier: inline, agent, fanout, max, factory,
  with the signals that chose it, the fan-out cap from the endpoint's real concurrency, and the
  owner's `[tier:x]` override.
- `card.py`: the intake card of every non-inline task: type, tier, new or continuation (board
  lookup), prior work (memory recall, verified lessons first), reuse candidates, and whether the
  plan must include a research step (nothing found).
- `research.py`: the closed researcher phase for "nothing found": jailed whatever the profile,
  network only, no token, its raw pages kept where no producer reads; konstant parses its cited
  summary and licence notes, refuses an uncited or instruction-shaped one, stores it in the shared
  memory pool, and hands producers only that summary.
- `licence.py`: the licence table the DoD rule `licence` (gate/rules/licence.py) applies to code
  a run copied from elsewhere.
"""
