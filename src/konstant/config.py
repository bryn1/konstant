"""konstant.toml: load, defaults, validation, and workspace-root resolution.

The workspace root (KONSTANT_HOME) is the install folder: it holds konstant.toml, var/ and
projects/. Resolution order: an explicit --config path (its directory), env KONSTANT_HOME, then
the nearest ancestor of the current directory that holds konstant.toml or var/board.db.

Validation fails closed: an unknown key in a known section, or a value of the wrong type, raises
ConfigError. A typo must stop the command, never silently fall back to a default that disarms a
gate (DESIGN §13).
"""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python >= 3.11
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as _toml

CONFIG_NAME = "konstant.toml"
ORIG_UMASK = None      # the caller's umask, set by the CLI entry point before it tightens it
LOOPBACK = ("127.0.0.1", "localhost", "::1")

DEFAULTS: dict = {
    "board": {
        "host": "127.0.0.1",
        "port": 8470,
        # the board speaks plain HTTP with bearer tokens: a non-loopback host needs this switch
        "allow_remote": False,
        "db": "var/board.db",
        "policy": {
            "verify_roles": ["verifier", "owner"],
            "review_roles": ["owner", "orchestrator", "verifier"],
            "reopen_roles": ["owner", "orchestrator"],
            "approve_roles": ["owner"],
            "evidence": "strict",
            "vacuity": "strict",
            "negative_control": "strict",
            "max_rounds": 3,
        },
    },
    "client": {"default_role": "orchestrator"},
    "catalog": {"path": ""},
    "harness": {
        # the agent CLI of the phases (docs/HARNESSES.md): claude | codex | gemini | dsh | command
        "name": "claude",
        # the model handed to the harness through its own model key ("" = the harness's default)
        "model": "",
        # workspace-scoped by design; the reasons are in gate/harness.py and DESIGN §9.
        # Used as written for name = "claude" and name = "command"; for the other names it is the
        # adapter's own command unless you change it here (then your template wins, {model} works)
        # --setting-sources project,local: no user-level settings/hooks; --strict-mcp-config: no
        # user MCP servers (REVIEW F-20)
        "command": ("claude -p --permission-mode dontAsk --setting-sources project,local "
                    "--strict-mcp-config --add-dir {workspace} --settings "
                    "{workspace}/.claude/settings.json {prompt}"),
        "stdin": False,
        "timeout_s": 3600,
        "max_parallel": 2,
        "env": {},
        # a local OpenAI-compatible endpoint (vLLM, llama.cpp, Ollama) for the adapters that can
        # speak to one (codex, dsh); base_url "" = the harness's own provider
        "endpoint": {"base_url": "", "api_key_env": ""},
        # per-type override: [harness.types.<type>] name / model / command (a phase runs on the
        # harness of its agent's type; the close-out runs on the default)
        "types": {},
    },
    # the reach of a harness session in this workspace (generated .claude/settings.json):
    # extra Claude Code permission rules (test runners etc.) and the Bash sandbox switch
    "permissions": {
        "allow": ["Bash(pytest *)", "Bash(python -m pytest *)", "Bash(python3 -m pytest *)"],
        "sandbox": True,
    },
    "gate": {
        "max_cycles": 3,
        "max_resumes": 3,
        "test_cmd": "auto",
        "cleanup": "warn",
        "verify_after_close": True,
        "hygiene": {"target": 250, "hard": 400, "tests": 600, "grown": 600},
        # run agent-written code (tests, the verifier's re-run, every dsh phase) inside
        # bubblewrap when it works
        "jail": True,
        # a gated dsh session (the konstant-gate plugin) files and claims a board job for a typed
        # task that names none ([job:N]); the task text is the brief, so it needs a DoD section
        "file_job": False,
    },
    # sealed holdout scenarios (docs/LEVEL5.md 3): each default is ONE key, so an owner answer to
    # the open questions (LEVEL5 9) is a config change
    "holdout": {
        "min_per_job": 2,              # sealed scenarios a holdout job needs (>= 1 proof)
        "max_failed_rounds": 2,        # failed verification rounds before the set counts as worn
        "run_timeout_s": 60,           # one scenario run in the verifier's jail
        # the sealed store: var/holdout (masked in every jail), or an absolute path OUTSIDE the
        # workspace readable only by a second OS user who runs the verifier (Q3, LEVEL5 3.8)
        "store": "var/holdout",
        # the scenario writer (docs/LEVEL5.md 3.4): "" = the default harness and model. Owner
        # decision Q1: one model may play every role; independence comes from identity, context
        # and the jail, so a second harness or model is optional, never required
        "writer_harness": "",
        "writer_model": "",
    },
    # level-5 intake (docs/LEVEL5.md 4): who may file a goal, and the limits a goal gets for what
    # it does not name. Only max_attempts is required (owner decision Q5); 0 = not limited
    "factory": {
        # `goal add` from a file: owner only; `goal add --from-chat` also these roles (the owner's
        # orchestrator session is the intake: 4.0). The public default keeps it to the owner
        "goal_roles": ["owner"],
        "defaults": {"max_attempts": 3, "wall_clock": "0", "max_task_runs": 0, "max_jobs": 0,
                     "max_rollbacks": 0, "max_tokens": 0, "max_cost_usd": 0,
                     "ship_target": "branch", "ship_branch": "main", "holdout_author": "agent"},
    },
    # where the factory's escalations go (docs/LEVEL5.md 6.3): stdout, file (var/factory/
    # notify.log) or chat (the gated dsh session shows them at the owner's next turn, 4.0);
    # webhook arrives with the factory loop (wave L5-5)
    "notify": {"kind": "stdout"},
    # ship-time owner decisions (docs/LEVEL5.md 5.4; owner decision Q4): jobs of these types are
    # filed `ship = decision` and never ship unattended
    "ship": {"decision_types": ["infra"]},
    "verify": {
        "rerun": True,
        "rerun_timeout_s": 900,
        "probe_timeout_s": 20,
        "path_roots": ["."],
        "url_hosts": ["127.0.0.1", "localhost"],
    },
}

# Tables whose keys are free-form (user data), not a schema.
_FREE_TABLES = {("harness", "env"), ("harness", "types"), ("factory", "defaults")}
HARNESS_NAMES = ("claude", "codex", "gemini", "dsh", "command")
TYPE_OVERRIDE_KEYS = ("name", "model", "command")


class ConfigError(Exception):
    """konstant.toml is malformed or names something unknown."""


@dataclass
class Config:
    home: Path
    data: dict = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    source: Path | None = None

    def section(self, *path: str) -> dict:
        cur = self.data
        for p in path:
            cur = cur[p]
        return cur

    @property
    def db_path(self) -> Path:
        return self.resolve(self.data["board"]["db"])

    @property
    def var(self) -> Path:
        return self.home / "var"

    @property
    def secrets_dir(self) -> Path:
        return self.var / "secrets"

    @property
    def base_url(self) -> str:
        b = self.data["board"]
        return f"http://{b['host']}:{b['port']}"

    def session_gate(self) -> dict:
        """[gate] plus `chat` ([notify] kind = "chat"): the dsh session plugin's settings."""
        return {**self.data["gate"], "chat": self.data["notify"]["kind"] == "chat"}

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.home / p


def _merge(base: dict, over: dict, where: tuple = ()) -> dict:
    out = copy.deepcopy(base)
    for key, val in over.items():
        here = where + (key,)
        name = ".".join(here)
        if key not in base:
            raise ConfigError(f"{CONFIG_NAME}: unknown key '{name}'")
        default = base[key]
        if isinstance(default, dict):
            if not isinstance(val, dict):
                raise ConfigError(f"{CONFIG_NAME}: '{name}' must be a table")
            out[key] = dict(val) if here in _FREE_TABLES else _merge(default, val, here)
            continue
        ok = (isinstance(val, bool) if isinstance(default, bool)
              else isinstance(val, int) and not isinstance(val, bool) if isinstance(default, int)
              else isinstance(val, type(default)))
        if not ok:
            raise ConfigError(f"{CONFIG_NAME}: '{name}' must be {type(default).__name__}, "
                              f"got {type(val).__name__} {val!r}")
        if isinstance(default, list) and not all(isinstance(x, str) for x in val):
            raise ConfigError(f"{CONFIG_NAME}: '{name}' must be a list of strings")
        out[key] = val
    return out


def is_loopback(host: str) -> bool:
    return host in LOOPBACK or host.startswith("127.")


def check_host(host: str, allow_remote: bool, where: str) -> None:
    if not is_loopback(host) and not allow_remote:
        raise ConfigError(f"{where}: host {host!r} is not loopback: the board speaks plain HTTP "
                          "with bearer tokens; set [board] allow_remote = true to accept that "
                          "(and put TLS in front of it)")


def _validate(data: dict, path) -> None:
    """Value checks the type merge cannot express (REVIEW F-24, F-32)."""
    b = data["board"]
    if not 1 <= b["port"] <= 65535:
        raise ConfigError(f"{path}: [board] port = {b['port']}: must be 1-65535")
    check_host(b["host"], b["allow_remote"], f"{path}: [board]")
    check_harness(data["harness"], path)
    check_holdout(data["holdout"], path)
    check_factory(data, path)


GOAL_ROLES = ("owner", "orchestrator")
NOTIFY_KINDS = ("stdout", "file", "chat")


def check_factory(data: dict, path) -> None:
    """[factory], [notify], [ship] and the scenario writer's harness (docs/LEVEL5.md 4, 6.3)."""
    roles = data["factory"]["goal_roles"]
    bad = [r for r in roles if r not in GOAL_ROLES]
    if bad or "owner" not in roles:
        raise ConfigError(f"{path}: [factory] goal_roles = {roles!r}: owner, optionally "
                          "orchestrator (a phase acts as worker and never files a goal)")
    from konstant.factory import goal as goal_mod
    try:
        goal_mod.check_defaults(data["factory"]["defaults"])
    except goal_mod.GoalError as exc:
        raise ConfigError(f"{path}: [factory] defaults: {exc}") from None
    if data["notify"]["kind"] not in NOTIFY_KINDS:
        raise ConfigError(f"{path}: [notify] kind = {data['notify']['kind']!r}: one of "
                          f"{', '.join(NOTIFY_KINDS)} (webhook arrives with the factory loop)")
    w = data["holdout"]["writer_harness"]
    if w and w not in HARNESS_NAMES:
        raise ConfigError(f"{path}: [holdout] writer_harness = {w!r}: one of "
                          f"{', '.join(HARNESS_NAMES)} or empty")
    m = data["holdout"]["writer_model"]
    if m and not _MODEL.fullmatch(m):
        raise ConfigError(f"{path}: [holdout] writer_model = {m!r} is not a model name")


def check_holdout(h: dict, path) -> None:
    for key in ("min_per_job", "max_failed_rounds", "run_timeout_s"):
        if h[key] < 1:
            raise ConfigError(f"{path}: [holdout] {key} = {h[key]}: must be >= 1")
    store = h["store"]
    if store != "var/holdout" and not os.path.isabs(store):
        raise ConfigError(f"{path}: [holdout] store = {store!r}: var/holdout (masked in every "
                          "jail) or an absolute path outside the workspace")


_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*")


def check_harness(h: dict, path) -> None:
    """[harness] values a typo must not silently change (docs/HARNESSES.md)."""
    where = f"{path}: [harness]"
    rows = [("", h)] + [(f".types.{t}", v) for t, v in h["types"].items()]
    for suffix, row in rows:
        if suffix and not isinstance(row, dict):
            raise ConfigError(f"{where}{suffix} must be a table (name, model, command)")
        if suffix:
            unknown = set(row) - set(TYPE_OVERRIDE_KEYS)
            if unknown:
                raise ConfigError(f"{where}{suffix}: unknown key '{sorted(unknown)[0]}' "
                                  f"(allowed: {', '.join(TYPE_OVERRIDE_KEYS)})")
            bad = [k for k, v in row.items() if not isinstance(v, str)]
            if bad:
                raise ConfigError(f"{where}{suffix}: '{bad[0]}' must be a string")
        name = row.get("name", "")
        if (name or not suffix) and name not in HARNESS_NAMES:
            raise ConfigError(f"{where}{suffix}: name = {name!r}: must be one of "
                              f"{', '.join(HARNESS_NAMES)}")
        model = row.get("model", "")
        if model and not _MODEL.fullmatch(model):
            raise ConfigError(f"{where}{suffix}: model = {model!r} is not a model name")
    ep = h["endpoint"]
    url = r"https?://[^\s/\"'\\]+(/[^\s\"'\\]*)?"
    if ep["base_url"] and not re.fullmatch(url, ep["base_url"]):
        raise ConfigError(f"{where}.endpoint: base_url must be an http(s) URL")
    if ep["api_key_env"] and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ep["api_key_env"]):
        raise ConfigError(f"{where}.endpoint: api_key_env must be an environment variable name")


def find_home(explicit_config: str | None = None, cwd: Path | None = None) -> Path:
    if explicit_config:
        return Path(explicit_config).resolve().parent
    env = os.environ.get("KONSTANT_HOME", "").strip()
    if env:
        return Path(env).resolve()
    here = (cwd or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / CONFIG_NAME).is_file() or (d / "var" / "board.db").is_file():
            return d
    raise ConfigError("no konstant workspace here: set KONSTANT_HOME, pass --config, or run "
                      "inside an installed konstant folder")


def load(home: Path | None = None, config_path: str | None = None) -> Config:
    home = home if home is not None else find_home(config_path)
    path = Path(config_path).resolve() if config_path else home / CONFIG_NAME
    data = copy.deepcopy(DEFAULTS)
    if path.is_file():
        try:
            raw = _toml.loads(path.read_text(encoding="utf-8"))
        except _toml.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        data = _merge(DEFAULTS, raw)
        _validate(data, path)
        return Config(home=home, data=data, source=path)
    if config_path:
        raise ConfigError(f"config file not found: {path}")
    return Config(home=home, data=data, source=None)
