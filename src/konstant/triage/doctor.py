"""`konstant doctor` rows for triage (docs/CONCEPTS.md "Triage"): the fan-out cap and where it
comes from, and whether the closed researcher can run here."""
from __future__ import annotations

from konstant.triage import tiers


def rows(cfg) -> list:
    cap, src = tiers.cap_of(cfg.data["harness"])
    out = [("INFO", "triage",
            f"fan-out cap {cap} typed run(s) at once: {src}"
            + ("" if cfg.data["harness"].get("max_concurrency") else
               "; set [harness] max_concurrency to your endpoint's slots to fan out wider"))]
    if cfg.data["triage"]["research"] == "off":
        out.append(("WARN", "research", "[triage] research = \"off\": a new task with nothing "
                    "similar on the board or in memory is planned without web research"))
        return out
    from konstant import jail
    if not cfg.data["gate"]["jail"] or not jail.available():
        out.append(("WARN", "research", "the closed researcher cannot run here (no working "
                    "bubblewrap jail, or [gate] jail = false): it never runs open, so a task "
                    "that needs research records it as unavailable"))
    else:
        out.append(("PASS", "research", "the closed researcher runs jailed: network only, $HOME "
                    "masked, no credentials, no token; producers see only its cited summary"))
    return out
