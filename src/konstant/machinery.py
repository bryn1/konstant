"""konstant's machinery paths and the credential locations: ONE source for every boundary (G-01,
G-03, G-04).

Every adapter's permission rendering (agents/settings.py for Claude Code, harnesses/codex.py,
harnesses/gemini.py) and konstant.jail's bind rules (the dsh phases, agent-written tests, verifier
re-runs) read these lists; tests/review/test_review2_harness.py checks that each entry has a rule
in every one of them. A phase may never write any of these paths, whatever the harness:

  - the release's own code and tools (bin/, .venv/, src/, catalog/, tests/, install.sh, ...),
  - every generated harness surface (.claude/, .agents/, .dsh/, .gemini/, AGENTS.md, CLAUDE.md):
    code or instructions that a LATER phase, or the operator's own unjailed session, loads,
  - var/harness/ (the relocated harness homes, among them the operator's `konstant dsh` session
    home: a profile layer planted there runs unjailed in that session), var/secrets/, the board DB
    and the other bookkeeping files under var/,
  - any .git/ directory (a .git/config or hook edit turns a later git command into arbitrary
    execution; shells that must commit get .git/config and .git/hooks read-only instead),
  - var/factory/ (the goal copies, the factory's events and the chat cursors: docs/LEVEL5.md 2.3;
    a phase that edited its goal or an event would steer the factory).

SEALED (docs/LEVEL5.md 2.3, 3.3) lists what no phase may even READ: the holdout store
var/holdout/. The jail masks it (jail.hidden), Claude Code's settings deny Read on it and
read-deny it in the sandbox, the codex profile denies it and the gemini policy denies its file
tools under it. No holdout content is ever stored anywhere else a phase can read.
"""
from __future__ import annotations

import os
from pathlib import Path

from konstant.board.policy import LABELS, PHASE_IDENTITIES

# workspace-relative directories no phase may write
DIRS = ("bin", ".venv", "src", "catalog", "tests",
        ".claude", ".agents", ".dsh", ".gemini",
        ".git", "var/secrets", "var/harness", "var/logs", "var/locks", "var/holdout",
        "var/factory")
# workspace-relative files no phase may write
FILES = ("konstant.toml", "install.sh", "get.sh", "pyproject.toml", "AGENTS.md", "CLAUDE.md",
         "var/board.db", "var/board.db-wal", "var/board.db-shm", "var/board.pid",
         "var/sessions.json")
# workspace-relative directories no phase may READ (the sealed holdout store; LEVEL5 2.3)
SEALED = ("var/holdout",)
# inside a git repository a shell may commit to: the parts that make git run commands
GIT_GUARDS = (".git/config", ".git/hooks")
# per run (var/runs/<run>/): the records konstant writes and the DoD check trusts
RUN_RECORDS = ("record.json", "phases", "prompts", "profiles", "evidence.md")
# role tokens a phase must never read (it acts as worker; viewer is read-only)
PRIVILEGED_TOKENS = ("owner.token", "orchestrator.token", "verifier.token")
# every token file of the workspace: the five roles and the factory identities (board/policy.py
# IDENTITIES; docs/LEVEL5.md 2.2). A phase reads only its own identity's token and the read-only
# viewer token (tokens_readable); the jail masks the rest, the codex profile denies them.
ALL_TOKENS = tuple(f"{label}.token" for label in LABELS)

# credential and agent-CLI homes under $HOME a phase never needs (the jail masks them, the codex
# profile denies them, the Claude sandbox read-denies them; docs/CONCEPTS.md lists the same set)
CREDENTIALS = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gcloud", "~/.config/gh", "~/.kube",
               "~/.docker", "~/.azure", "~/.netrc", "~/.git-credentials", "~/.pypirc",
               "~/.npmrc", "~/.cargo/credentials.toml", "~/.config/hub",
               "~/.claude", "~/.claude.json", "~/.codex", "~/.gemini", "~/.dsh",
               "~/.config/anthropic", "~/.config/openai")
# credential environment variables a phase does not get unless [confinement] credentials passes
# them (konstant/confinement.py; a harness's own API key, e.g. ANTHROPIC_API_KEY, is not here: the
# harness needs it to reach its model)
CREDENTIAL_ENV = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                  "AZURE_CLIENT_SECRET", "GOOGLE_APPLICATION_CREDENTIALS", "GH_TOKEN",
                  "GITHUB_TOKEN", "GITLAB_TOKEN", "HF_TOKEN", "NPM_TOKEN", "TWINE_PASSWORD",
                  "VAULT_TOKEN", "KUBECONFIG", "DIGITALOCEAN_ACCESS_TOKEN", "CLOUDFLARE_API_TOKEN")
# the docker daemon's usual sockets (root-equivalent: [confinement] docker_socket)
DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")
# an agent CLI's own home may be relocated by an environment variable: masked as well
HOME_ENV = ("DSH_HOME", "DSH_AGENTS_HOME", "CODEX_HOME", "GEMINI_CLI_HOME", "CLAUDE_CONFIG_DIR")
# a harness whose own sandboxed commands need its home keeps it, minus its credential files
SELF_HOME = {"claude": ("~/.claude", ("~/.claude/.credentials.json",)),
             "codex": ("~/.codex", ("~/.codex/auth.json",))}


def tokens_readable(identity: str = "worker") -> tuple:
    """The token files a phase acting as `identity` reads: its own and the read-only viewer's."""
    if identity not in PHASE_IDENTITIES:
        raise ValueError(f"{identity!r} is not an identity a phase acts as "
                         f"({', '.join(PHASE_IDENTITIES)})")
    return (f"{identity}.token", "viewer.token")


def tokens_denied(identity: str = "worker") -> tuple:
    """Every other token file: what that phase must never read (the privileged roles AND the
    other worker identities: the board's label guards rely on it, docs/LEVEL5.md 2.2)."""
    keep = tokens_readable(identity)
    return tuple(t for t in ALL_TOKENS if t not in keep)


def dirs(ws) -> list:
    return [Path(ws) / d for d in DIRS]


def sealed(ws) -> list:
    """The absolute sealed paths of workspace `ws` (read at call time: tests empty SEALED)."""
    return [Path(ws) / d for d in SEALED]


def files(ws) -> list:
    return [Path(ws) / f for f in FILES]


def credentials(harness: str | None = None, env=None) -> list:
    """The credential locations, `~`-form, plus the agent homes named by HOME_ENV. For `harness`
    in SELF_HOME its own home is replaced by its credential files (its sandbox needs the rest)."""
    env = os.environ if env is None else env
    out = list(CREDENTIALS)
    if harness in SELF_HOME:
        own, keep = SELF_HOME[harness]
        out = [c for c in out if c != own] + list(keep)
    for var in HOME_ENV:
        if env.get(var):
            out.append(env[var])
    return list(dict.fromkeys(out))


def jail_read_only(ws) -> list:
    """Absolute paths the jail binds read-only whenever a writable bind contains them: every
    machinery path plus all of var/ (only a run's own OUT is reopened)."""
    ws = Path(ws)
    return [*dirs(ws), *files(ws), ws / "var"]


def git_guards(root) -> list:
    return [Path(root) / g for g in GIT_GUARDS]
