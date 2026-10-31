"""The harness adapter (DESIGN §9): argv templates, never a shell, env, logs, timeout."""
from __future__ import annotations

import sys

import pytest

from konstant.config import DEFAULTS
from konstant.gate import harness
from konstant.gate.harness import Harness, HarnessError, build_argv

V = {"prompt": "do {agent} it", "prompt_file": "/r/p.md", "agent": "coder", "cwd": "/c",
     "run_dir": "/r", "workspace": "/w"}


def test_default_command_is_workspace_scoped():
    assert DEFAULTS["harness"]["command"] == harness.DEFAULT_COMMAND
    argv = build_argv(harness.DEFAULT_COMMAND, V, False)
    assert argv[:9] == ["claude", "-p", "--permission-mode", "dontAsk", "--setting-sources",
                        "project,local", "--strict-mcp-config", "--add-dir", V["workspace"]]
    assert argv[9] == "--settings"
    assert argv[10] == "/w/.claude/settings.json" and argv[-1] == "do {agent} it"


def test_placeholders_are_one_pass_and_one_argv_item():
    argv = build_argv("tool --a={agent} {prompt} --f {prompt_file} {cwd}", V, False)
    assert argv == ["tool", "--a=coder", "do {agent} it", "--f", "/r/p.md", "/c"]


@pytest.mark.parametrize("template,stdin,needle", [
    ("", False, "empty"),
    ("tool --x", False, "needs {prompt}"),
    ("tool 'unclosed", False, "does not split"),
])
def test_build_argv_refusals(template, stdin, needle):
    with pytest.raises(HarnessError, match=needle):
        build_argv(template, V, stdin)


def test_stdin_mode_needs_no_placeholder():
    assert build_argv("tool --x", V, True) == ["tool", "--x"]


def test_argv_prompt_limit_red_and_green():
    big = dict(V, prompt="x" * (harness.ARGV_PROMPT_MAX + 1))
    with pytest.raises(HarnessError, match="prompt_file"):
        build_argv("tool {prompt}", big, False)
    assert build_argv("tool {prompt_file}", big, False) == ["tool", "/r/p.md"]


def test_run_sets_the_task_env_and_logs(tmp_path):
    script = ("import os,sys; print(os.environ['KONSTANT_IN_TASK'], os.environ['KONSTANT_ROLE'], "
              "os.environ['KONSTANT_RUN'], os.environ['EXTRA'], open(sys.argv[1]).read())")
    h = Harness(f"{sys.executable} -c \"{script}\" {{prompt_file}}", env={"EXTRA": "e1"},
                workspace=tmp_path)
    res = h.run("PROMPT-TEXT", agent="coder", cwd=tmp_path, run_dir=tmp_path / "run", label="01-x")
    log = open(res.log).read()
    assert res.rc == 0 and log.startswith("1 worker ") and "e1 PROMPT-TEXT" in log
    pf = tmp_path / "run" / "prompts" / "01-x.md"
    assert oct(pf.stat().st_mode & 0o777) == "0o600"


def test_run_stdin_mode(tmp_path):
    h = Harness(f"{sys.executable} -c \"import sys; print(sys.stdin.read().upper())\"", stdin=True,
                workspace=tmp_path)
    res = h.run("hello", agent="a", cwd=tmp_path, run_dir=tmp_path, label="s")
    assert "HELLO" in open(res.log).read()


def test_run_timeout_kills_the_group(tmp_path):
    h = Harness(f"{sys.executable} -c \"import time; time.sleep(30)\" {{prompt_file}}",
                timeout_s=1, workspace=tmp_path)
    res = h.run("x", agent="a", cwd=tmp_path, run_dir=tmp_path, label="t")
    assert res.timed_out and res.rc == 124 and res.seconds < 10


def test_run_missing_binary_is_127(tmp_path):
    h = Harness("no-such-harness-binary {prompt_file}", workspace=tmp_path)
    assert h.run("x", agent="a", cwd=tmp_path, run_dir=tmp_path, label="m").rc == 127


def test_cli_template_absolutises_existing_relative_paths(tmp_path, monkeypatch):
    from konstant.cli.task_run import cli_template
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "h.py").write_text("")
    monkeypatch.chdir(tmp_path)
    out = cli_template("python3 fx/h.py {prompt_file} --flag=a/b missing/x.py")
    assert out == f"python3 {tmp_path}/fx/h.py '{{prompt_file}}' --flag=a/b missing/x.py"
