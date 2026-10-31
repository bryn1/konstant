"""Gate and permission findings: F-16 (classifier), F-07/F-08/F-19 (generated settings),
F-20 (user-level context in the default harness), F-06 (task check jailed)."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from konstant import catalog
from konstant.agents import settings
from konstant.config import DEFAULTS
from konstant.gate import check
from konstant.gate.classify import classify

CAT = catalog.load()


@pytest.mark.parametrize("task", [
    "ok, implement the OAuth server in auth.py with tests",
    "list the steps, then refactor module billing.py and ship it",
    "Can you implement a rate limiter in limiter.py and add tests?",
    "hi! please fix the bug in parser.py",
    "add retries to the http client",
])
def test_F16_conversational_openers_do_not_ungate_real_work(task):
    t, why = classify(task, CAT)
    assert t is not None, (task, why)


@pytest.mark.parametrize("task", ["what is the board?", "thanks", "hi!", "ok",
                                  "show me the open jobs", "how do I add a project?",
                                  "what files does the parser module touch?"])
def test_F16_chat_and_questions_stay_small(task):
    assert classify(task, CAT)[0] is None


def _render(tmp_path):
    return json.loads(settings.render(tmp_path, {"allow": [], "sandbox": True}, "python3"))


def test_F07_project_git_dirs_are_not_editable(tmp_path):
    data = _render(tmp_path)
    ws = settings.abs_rule(tmp_path)
    assert f"Edit({ws}/**/.git/**)" in data["permissions"]["deny"]


def test_F07_git_init_is_not_allowed(tmp_path):
    allow = _render(tmp_path)["permissions"]["allow"]
    assert not any(r.startswith("Bash(git init") for r in allow)


def test_F08_catalog_and_tool_files_are_not_editable(tmp_path):
    deny = _render(tmp_path)["permissions"]["deny"]
    ws = settings.abs_rule(tmp_path)
    for p in ("catalog/**", "tests/**"):
        assert f"Edit({ws}/{p})" in deny, p
    for f in ("install.sh", "pyproject.toml"):
        assert f"Edit({ws}/{f})" in deny, f


def test_F19_the_allow_list_stays_authoritative_in_the_sandbox(tmp_path):
    sb = _render(tmp_path)["sandbox"]
    assert sb["autoAllowBashIfSandboxed"] is False
    assert any(p.endswith("/.ssh") for p in sb["filesystem"]["denyRead"])


def test_F20_default_harness_skips_user_settings_and_mcp():
    cmd = DEFAULTS["harness"]["command"]
    assert "--setting-sources project,local" in cmd and "--strict-mcp-config" in cmd


def _jail_ok() -> bool:
    if not shutil.which("bwrap"):
        return False
    r = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                        "--unshare-pid", "true"], capture_output=True)
    return r.returncode == 0


@pytest.mark.skipif(not _jail_ok(), reason="bubblewrap cannot run here")
def test_F06_agent_tests_run_by_task_check_cannot_write_the_workspace(scen):
    s = scen().good()
    escape = s.ws / "ESCAPED.txt"
    s.write("test_escape.py", f"def test_escape():\n    open({str(escape)!r}, 'w').write('x')\n")
    s.check()
    assert not escape.exists(), "task check ran agent test code with write access outside OUT"


@pytest.mark.skipif(not _jail_ok(), reason="bubblewrap cannot run here")
def test_F06_agent_tests_cannot_read_the_token_dir(scen):
    s = scen().good()
    (s.ws / "var" / "secrets").mkdir(parents=True)
    (s.ws / "var" / "secrets" / "owner.token").write_text("TOPSECRET\n")
    leak = s.out / "leak.txt"
    s.write("test_leak.py", "import pathlib\n\n\ndef test_leak():\n    p = pathlib.Path("
            f"{str(s.ws / 'var' / 'secrets' / 'owner.token')!r})\n"
            f"    pathlib.Path({str(leak)!r}).write_text(p.read_text() if p.exists() else '')\n")
    s.check()
    assert "TOPSECRET" not in (leak.read_text() if leak.exists() else "")
