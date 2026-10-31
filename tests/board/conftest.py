"""Board test harness: a temp workspace, a migrated DB, one token per role, a TestClient."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from konstant import config
from konstant.board import auth, db, migrate
from konstant.board.app import create_app
from konstant.board.policy import ROLES


class Board:
    def __init__(self, home, policy: dict | None = None):
        self.home = home
        toml = ""
        if policy:
            toml = "[board.policy]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in policy.items())
        (home / "konstant.toml").write_text(toml)
        self.cfg = config.load(home)
        migrate.migrate(self.cfg.db_path)
        with db.transaction(self.cfg.db_path) as conn:
            auth.mint_missing(conn, self.cfg.secrets_dir)
        self.tokens = {r: auth.read_token(self.cfg.secrets_dir, r) for r in ROLES}
        self.client = TestClient(create_app(self.cfg))
        self.root = self.call("owner", "POST", "/api/projects", {"slug": "demo"}).json()["root_job_id"]

    def headers(self, role_or_token: str) -> dict:
        token = self.tokens.get(role_or_token, role_or_token)
        return {"Authorization": f"Bearer {token}"}

    def call(self, who: str, method: str, path: str, body=None):
        return self.client.request(method, path, json=body, headers=self.headers(who))

    def add_token(self, role: str, label: str) -> str:
        """An extra token, e.g. an owner-role token carrying another identity's label."""
        value = f"test-{role}-{label}-token-value"
        with db.transaction(self.cfg.db_path) as conn:
            conn.execute("INSERT INTO tokens (role, label, sha256) VALUES (?,?,?)",
                         (role, label, auth.sha256(value)))
        return value

    def insert_job(self, status: str = "queued", *, type: str = "docs", parent: int | None = None,
                   requested_by: str = "orchestrator", assignee: str | None = None,
                   closed_by: str | None = None, after_id: int | None = None,
                   title: str = "a job") -> int:
        """Put a job straight into a state (the API only reaches states by verbs)."""
        with db.transaction(self.cfg.db_path) as conn:
            return conn.execute(
                "INSERT INTO jobs (project_id, parent_id, type, title, brief, acceptance, status, "
                "requested_by, assignee, closed_by, after_id) VALUES (1,?,?,?,?,?,?,?,?,?,?)",
                (parent or self.root, type, title, "DoD: x", "DoD: x", status, requested_by,
                 assignee, closed_by, after_id)).lastrowid

    def status(self, job_id: int) -> str:
        with db.reading(self.cfg.db_path) as conn:
            return conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0]

    def add(self, who: str = "orchestrator", **body):
        payload = {"title": "T: a job", "project": "demo", "type": "code",
                   "brief": "Do it.\nDoD: tests pass (pytest exits 0)"}
        payload.update(body)
        return self.call(who, "POST", "/api/jobs", payload)


GOOD_EVIDENCE = {"verify_cmd": "pytest -q", "verify_exit": 0,
                 "verify_output": "12 passed in 0.31s", "docs": "n/a - test"}


@pytest.fixture()
def board(tmp_path):
    return Board(tmp_path)


@pytest.fixture()
def make_board(tmp_path):
    counter = {"n": 0}

    def make(policy=None):
        counter["n"] += 1
        home = tmp_path / f"ws{counter['n']}"
        home.mkdir()
        return Board(home, policy)
    return make


@pytest.fixture(scope="module")
def shared_board(tmp_path_factory):
    return Board(tmp_path_factory.mktemp("shared"))
