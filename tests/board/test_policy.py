"""[board.policy]: fail-closed defaults, malformed values stop the board, role sets are live."""
from __future__ import annotations

import pytest

from konstant import config
from konstant.board import migrate, policy
from konstant.board.app import StartupError, create_app
from tests.board.conftest import GOOD_EVIDENCE


def test_defaults():
    p = policy.from_mapping({})
    assert p.verify_roles == ("verifier", "owner")
    assert "orchestrator" not in p.verify_roles          # the driver cannot self-serve verified
    assert p.review_roles == ("owner", "orchestrator", "verifier")   # F-03: + self-review refused
    assert p.reopen_roles == ("owner", "orchestrator")
    assert p.approve_roles == ("owner",)
    assert (p.evidence, p.vacuity, p.negative_control, p.max_rounds) == ("strict",) * 3 + (3,)


@pytest.mark.parametrize("empty", [[], "", None, " , "])
def test_an_empty_role_list_means_the_default_never_nobody(empty):
    assert policy.from_mapping({"verify_roles": empty}).verify_roles == ("verifier", "owner")


@pytest.mark.parametrize("section,needle", [
    ({"verify_roles": ["verifer"]}, "unknown role"),
    ({"verify_roles": ["viewer"]}, "read-only"),
    ({"verify_roles": "verifier;owner"}, "unknown role"),
    ({"evidence": "strcit"}, "must be one of"),
    ({"vacuity": "on"}, "must be one of"),
    ({"max_rounds": 0}, "max_rounds"),
    ({"max_rounds": True}, "max_rounds"),
    ({"verify_role": ["owner"]}, "unknown key"),
])
def test_a_malformed_value_raises(section, needle):
    with pytest.raises(policy.PolicyError, match=needle):
        policy.from_mapping(section)


def test_configured_order_is_kept_and_deduplicated():
    assert policy.from_mapping({"verify_roles": ["owner", "verifier", "owner"]}).verify_roles == \
        ("owner", "verifier")


def test_the_board_refuses_to_start_on_a_malformed_policy(tmp_path):
    (tmp_path / "konstant.toml").write_text('[board.policy]\nverify_roles = ["verifer"]\n')
    cfg = config.load(tmp_path)
    migrate.migrate(cfg.db_path)
    with pytest.raises(policy.PolicyError):
        create_app(cfg)


def test_the_board_refuses_to_start_on_a_stale_schema(tmp_path):
    cfg = config.load(tmp_path)
    with pytest.raises(StartupError, match="board init"):
        create_app(cfg)


def test_a_typo_in_konstant_toml_stops_the_command(tmp_path):
    (tmp_path / "konstant.toml").write_text("[board]\nprot = 9\n")
    with pytest.raises(config.ConfigError, match="unknown key 'board.prot'"):
        config.load(tmp_path)


def _closed(b):
    job = b.insert_job("claimed", requested_by="orchestrator", assignee="orchestrator")
    assert b.call("orchestrator", "POST", f"/api/jobs/{job}/close", GOOD_EVIDENCE).status_code == 200
    return job


def test_verify_roles_from_config_are_what_the_board_enforces(make_board):
    narrow = make_board({"verify_roles": ["verifier"]})
    job = _closed(narrow)
    res = narrow.call("owner", "POST", f"/api/jobs/{job}/verdict", {"verdict": "PASS"})
    assert res.status_code == 403 and "requires role verifier" in res.json()["detail"]
    default = make_board()
    job = _closed(default)
    assert default.call("owner", "POST", f"/api/jobs/{job}/verdict",
                        {"verdict": "PASS"}).status_code == 200


def test_max_rounds_from_config(make_board):
    b = make_board({"max_rounds": 1})
    job = b.insert_job("completed_unverified", closed_by="orchestrator")
    b.call("verifier", "POST", f"/api/jobs/{job}/verdict", {"verdict": "FAIL", "reason": "no"})
    assert b.status(job) == "blocked"
