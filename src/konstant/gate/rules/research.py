"""Rule `research` (docs/CONCEPTS.md "Triage"). UNEXCUSABLE.

When the run's intake card (record.json `card`, computed by konstant before any planning) says
`research_required` (a new task, nothing similar on the board or in memory), the plan must have
included the research step: konstant's closed researcher ran for THIS run and left its result in
the research store (`var/research/<run>/result.json`, machinery: no phase writes it). The runner
does that itself before the first phase; an interactive session runs `konstant task research
<run>`. A result of any outcome satisfies the rule (a refused or empty summary is an honest
outcome the producers were told about); a missing one is UNMET (owner orchestrator: the session
that planned without it). A researcher that could not run closed here (no jail) is recorded as
`unavailable`: the rule warns, because the researcher never runs open.
"""
from __future__ import annotations

from konstant.gate.rules.common import Finding, Run


def check(run: Run) -> list:
    card = run.rec.get("card") or {}
    if not card.get("research_required"):
        return []
    from konstant.triage import research
    res = research.load_result(run.workspace or run.run_dir.parent.parent.parent, run.run_dir)
    if res is None:
        return [Finding("research", "the intake card requires a research step (nothing similar "
                                    "was found) and none ran for this run: run `konstant task "
                                    f"research {run.run_dir}` before planning", owner="orchestrator")]
    if res.get("state") == "unavailable":
        return [Finding("research", "the research step could not run closed here ("
                        + "; ".join(res.get("reasons") or [])[:200] + "); the plan went on "
                        "without web research", severity="warn")]
    return []
