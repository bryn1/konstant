"""Rule `cleanup`: DONE.md carries `CLEANUP: <what was moved/removed and where>` or
`CLEANUP: NONE-NEEDED`. `[gate] cleanup = warn` (default: a stderr note) or `fail` (UNMET).
Applied only when DONE.md exists (rule `done` names a missing one)."""
from __future__ import annotations

from konstant.gate.rules.common import Finding, Run


def check(run: Run) -> list:
    path = run.out / "DONE.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if any(ln.lstrip().startswith("CLEANUP:") and ln.split(":", 1)[1].strip()
           for ln in text.splitlines()):
        return []
    mode = run.gate.get("cleanup", "warn")
    return [Finding("cleanup", "DONE.md carries no CLEANUP: line - state what this run cleaned or "
                               "moved and where, or `CLEANUP: NONE-NEEDED`",
                    severity="unmet" if mode == "fail" else "warn")]
