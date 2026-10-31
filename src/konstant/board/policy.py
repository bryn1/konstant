"""Board policy: role sets and evidence switches from konstant.toml [board.policy].

Fail-closed rules:
- an empty or missing role list means the DEFAULT, never "nobody" - a blank line must not lock
  every caller out;
- a malformed value (unknown role, unknown mode, non-positive max_rounds) raises PolicyError, and
  the board refuses to start - a typo must stop the board, not silently disarm a gate;
- the verify default is verifier + owner. `orchestrator` is not in it: the identity that drives
  and closes work must not be able to self-serve the terminal `verified`;
- `review` (the other terminal state) is refused to the identity that filed, claimed or closed
  the job whatever its role (lifecycle.review), so the orchestrator can review work a worker
  filed and claimed, never its own; owner and verifier review the rest (REVIEW F-03).
"""
from __future__ import annotations

from dataclasses import dataclass

ROLES = ("owner", "orchestrator", "worker", "verifier", "viewer")
WRITE_ROLES = ("owner", "orchestrator", "worker", "verifier")
MODES = ("off", "warn", "strict")

DEFAULT_ROLE_SETS = {
    "verify_roles": ("verifier", "owner"),
    "review_roles": ("owner", "orchestrator", "verifier"),
    "reopen_roles": ("owner", "orchestrator"),
    "approve_roles": ("owner",),
}
DEFAULT_MODES = {"evidence": "strict", "vacuity": "strict", "negative_control": "strict"}
DEFAULT_MAX_ROUNDS = 3


class PolicyError(Exception):
    """[board.policy] holds a value the board will not guess about."""


@dataclass(frozen=True)
class Policy:
    verify_roles: tuple = DEFAULT_ROLE_SETS["verify_roles"]
    review_roles: tuple = DEFAULT_ROLE_SETS["review_roles"]
    reopen_roles: tuple = DEFAULT_ROLE_SETS["reopen_roles"]
    approve_roles: tuple = DEFAULT_ROLE_SETS["approve_roles"]
    evidence: str = "strict"
    vacuity: str = "strict"
    negative_control: str = "strict"
    max_rounds: int = DEFAULT_MAX_ROUNDS

    def roles(self, key: str) -> tuple:
        return getattr(self, key)


def _role_set(name: str, raw) -> tuple:
    """Configured order is kept (it is the order refusals name the roles in); duplicates drop."""
    if raw is None or raw == [] or raw == "":
        return DEFAULT_ROLE_SETS[name]
    if isinstance(raw, str):
        raw = [r.strip() for r in raw.split(",") if r.strip()]
        if not raw:
            return DEFAULT_ROLE_SETS[name]
    if not isinstance(raw, (list, tuple)) or not all(isinstance(r, str) for r in raw):
        raise PolicyError(f"[board.policy] {name} must be a list of role names")
    unknown = sorted(set(raw) - set(ROLES))
    if unknown:
        raise PolicyError(f"[board.policy] {name} names unknown role(s) {', '.join(unknown)}; "
                          f"roles are {', '.join(ROLES)}")
    if "viewer" in raw:
        raise PolicyError(f"[board.policy] {name} may not include the read-only role 'viewer'")
    return tuple(dict.fromkeys(raw))


def from_mapping(section: dict | None) -> Policy:
    section = dict(section or {})
    unknown = sorted(set(section) - set(DEFAULT_ROLE_SETS) - set(DEFAULT_MODES) - {"max_rounds"})
    if unknown:
        raise PolicyError(f"[board.policy] unknown key(s): {', '.join(unknown)}")
    kwargs = {name: _role_set(name, section.get(name)) for name in DEFAULT_ROLE_SETS}
    for name, default in DEFAULT_MODES.items():
        mode = section.get(name) or default
        if mode not in MODES:
            raise PolicyError(f"[board.policy] {name} = {mode!r}; must be one of {', '.join(MODES)}")
        kwargs[name] = mode
    rounds = section.get("max_rounds", DEFAULT_MAX_ROUNDS)
    if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
        raise PolicyError(f"[board.policy] max_rounds = {rounds!r}; must be an integer >= 1")
    kwargs["max_rounds"] = rounds
    return Policy(**kwargs)
