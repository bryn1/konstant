"""Stdlib HTTP client for the board (urllib only, so `bin/konstant job ...` starts fast).

Token choice is by role or factory identity (`--as LABEL`, default [client] default_role): the
token file is var/secrets/<label>.token. Under a task run (KONSTANT_IN_TASK=1) a phase acts as
`worker` (its default; KONSTANT_ROLE is honoured only when it names worker or viewer) and every
other token is refused: a phase agent must not verify its own work, act as the owner, or act as
the orchestrator that filed and claimed its job (DESIGN §5, REVIEW F-12). The worker token a
phase uses is the one of its IDENTITY (KONSTANT_IDENTITY: worker, or a factory identity such as
scenario; docs/LEVEL5.md 2.2), the only worker-role token its jail lets it read.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from konstant.config import Config

GUARDED_ROLES = ("verifier", "owner")
IN_TASK_ROLES = ("worker", "viewer")


def in_task() -> bool:
    return os.environ.get("KONSTANT_IN_TASK") == "1"


def default_role(configured: str) -> str:
    """The role a command acts as when no --as is given: worker inside a task run."""
    if in_task():
        env = os.environ.get("KONSTANT_ROLE", "worker")
        return env if env in IN_TASK_ROLES else "worker"
    return configured


class ClientError(Exception):
    """A refusal or failure to report to the user. `status` is the HTTP code, 0 if none."""

    def __init__(self, message: str, status: int = 0, exit_code: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.exit_code = exit_code          # overrides the CLI's 1/2 mapping when set


def identity() -> str:
    """The identity of the phase this process runs in (worker unless the runner named another
    worker identity)."""
    from konstant.board.policy import PHASE_IDENTITIES
    ident = os.environ.get("KONSTANT_IDENTITY", "worker")
    return ident if ident in PHASE_IDENTITIES else "worker"


def token_for(cfg: Config, role: str) -> str:
    """The token of `role` (a role, or a factory identity's label)."""
    label = role
    if in_task():
        if role in ("worker", identity()):
            label = identity()                    # the phase's own identity token
        elif role != "viewer":
            raise ClientError(f"refused: --as {role} is not available inside a task run "
                              "(KONSTANT_IN_TASK=1): a phase acts as its own identity "
                              f"({identity()}, role worker) or viewer; verification, owner and "
                              "orchestrator actions happen outside it")
    path = cfg.secrets_dir / f"{label}.token"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise ClientError(f"no token for {label!r} at {path} (run `konstant board init`)")
    except PermissionError:
        raise ClientError(f"cannot read {path}: this OS user has no access to the {label} token")
    if not value:
        raise ClientError(f"token file {path} is empty")
    return value


class Client:
    def __init__(self, base_url: str, token: str = "", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body=None, params=None) -> dict:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v not in (None, "", False)}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw).get("detail", raw.decode("utf-8", "replace"))
            except (ValueError, AttributeError):
                detail = raw.decode("utf-8", "replace")
            if not isinstance(detail, str):
                detail = json.dumps(detail)
            raise ClientError(f"HTTP {exc.code}: {detail}", exc.code) from None
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ClientError(f"board unreachable at {self.base_url} ({reason}); "
                              "start it with `konstant board start`") from None
        return json.loads(raw) if raw else {}

    def get(self, path: str, **params) -> dict:
        return self.request("GET", path, params=params)

    def post(self, path: str, body=None) -> dict:
        return self.request("POST", path, body=body if body is not None else {})

