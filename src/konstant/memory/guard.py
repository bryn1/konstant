"""Memory's integrity rules (docs/LEVEL5.md 2.2, 3.3; docs/CONCEPTS.md "Memory").

Memory is a channel BETWEEN jobs. Owner decision 2026-11-08: agents learn from each other's
memory, through ONE-WAY GLASS:

- **The shared pool** (`shared/`): every producing identity (worker: the coder, tester,
  reviewer and every other phase; planner, dod-reviewer, orchestrator, factory, owner) reads AND
  writes it, so every agent recalls every earlier job's notes and lessons.
- **The sealed pool** (`sealed/`): the scenario writer and the verifier READ the shared pool but
  WRITE only here, and no producer (nor the viewer, nor the web view) reads it: it is inside the
  integrity core like the holdout store. The owner reads both.
- **Source identity per note.** Inside a pool a note lives in its writer's folder
  (`shared/worker/...`, `sealed/scenario/...`); the board takes the writer from the caller's
  token, never from the request, and every write is attributed (`memory_writes`, the vault
  commit's author, the note's `actor`). Recall labels each note with its job and whether that job
  reached `verified` (service.py), and ranks verified-job lessons first.
- **Notes konstant did not write** (an owner's own note, a file anything else dropped into
  `memory/`) are served only when `[confinement] memory_share` is on (the open profile's
  default); folders outside the two pools are pool OWN_NOTES, read like the shared pool. A hand
  note under `sealed/` stays sealed.
- **Store-time scan.** Nothing from the sealed holdout store enters memory: a canary-shaped
  string, a pasted scenario, or a distinctive literal of any sealed scenario that is not in its own
  job's brief is refused, and the refusal is recorded (and, for a phase of a job, written on that
  job's trail, which the verifier reads as LEAK or LEAK-SUSPECT: verify/holdout.py).
"""
from __future__ import annotations

import re
from pathlib import Path

from konstant.board.policy import LABELS
from konstant.holdout import lint

SHARED, SEALED = "shared", "sealed"
OWN_NOTES = "notes"
POOLS = (SHARED, SEALED, OWN_NOTES)
# the identities behind the glass: they read the shared pool, write only the sealed one
JUDGES = ("scenario", "verifier")
_SCENARIO_LINE = re.compile(r"(?m)^(SCENARIO|KIND|RUN|EXPECT_EXIT|EXPECT_OUT|EXPECT_RE|HINT|"
                            r"CANARY):")
CANARY_ANY = re.compile(r"khc-[0-9a-f]{20}")


class StoreRefused(Exception):
    """A write memory must not take. `kind`: canary | scenario | literal | unreadable."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


def pool_of(rel: str) -> str:
    """The pool of a vault path: its top folder when that is a pool, else OWN_NOTES (the owner's
    own folders, a note at the vault root)."""
    top = rel.split("/", 1)[0] if "/" in rel else ""
    return top if top in (SHARED, SEALED) else OWN_NOTES


def readable(label: str) -> set:
    """The pools identity `label` recalls from: the sealed one only from behind the glass."""
    return set(POOLS) if label == "owner" or label in JUDGES else {SHARED, OWN_NOTES}


def can_read(label: str, rel: str) -> bool:
    return pool_of(rel) in readable(label)


def write_pool(label: str) -> str:
    """Where `label` writes (the token decides, not the request): the judges into the sealed
    pool, every other identity into the shared one; the viewer nowhere."""
    if label not in LABELS or label == "viewer":
        raise StoreRefused("identity", f"{label!r} does not write memory")
    return SEALED if label in JUDGES else SHARED


def scenarios(store_root: Path) -> list:
    """[(job id, raw bytes)] of every scenario file in the sealed store (sealed sets, drafts and
    retired sets alike). Raises PermissionError when the store exists but cannot be read."""
    out = []
    root = Path(store_root)
    if not root.exists():
        return out
    for job in sorted(root.iterdir()):
        if not job.is_dir() or not job.name.isdigit():
            continue
        for sub in (job, job / "drafts"):
            if not sub.is_dir():
                continue
            for f in sorted(sub.iterdir()):
                if f.is_file() and f.suffix == ".scenario":
                    out.append((int(job.name), f.read_bytes()))
    return out


def scan(text: str, store_root: Path, briefs) -> None:
    """Refuse `text` (StoreRefused) when it carries anything from the sealed store. `briefs`:
    job id -> the job's brief + acceptance (a literal the job's own brief shows is public)."""
    if CANARY_ANY.search(text):
        raise StoreRefused("canary", "refused: the note carries a holdout canary (khc-...); "
                           "nothing from the sealed holdout store enters memory")
    if len(_SCENARIO_LINE.findall(text)) >= 3:
        raise StoreRefused("scenario", "refused: the note has the shape of a holdout scenario "
                           "(SCENARIO/RUN/EXPECT lines); scenarios never enter memory")
    try:
        found = scenarios(store_root)
    except OSError:
        raise StoreRefused("unreadable", "refused: the sealed holdout store cannot be read, so "
                           "the note cannot be checked against it (fail closed)") from None
    low = text.lower()
    for job, raw in found:
        try:
            sc = lint.parse(raw, "H0")
        except lint.ScenarioError:
            continue
        public = (briefs(job) or "").lower()
        if any(x.lower() in low for x in lint.literals(sc) if x.lower() not in public):
            raise StoreRefused("literal", "refused: the note carries a literal of a sealed "
                               "holdout scenario (recorded; for a job's phase the verifier "
                               "counts it as a LEAK-SUSPECT of that job)")
