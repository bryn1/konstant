"""How the workspace-scoped reach (design decision: edits and commands only inside the workspace,
deny the rest) maps onto each harness's own permission system; red and green both ways."""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest
import yaml

from konstant import catalog
from konstant.agents.generate import Generator
from konstant.config import _toml
from konstant.harnesses import codex as codex_mod
from konstant.harnesses.base import Phase
from tests.harness.conftest import REAL_HOME, hcfg, values

CAT = catalog.load()


def profile(ws):
    return codex_mod.filesystem(Phase(values(ws)))


def test_codex_profile_workspace_writable_rest_read_only(ws, home):
    fs = profile(ws)
    assert fs[":root"] == "read" and fs[str(ws)] == "write"
    assert not any(k in ("/tmp", ":slash_tmp", ":tmpdir") for k in fs)       # /tmp NOT writable
    assert [k for k, v in fs.items() if v == "write"] == [
        str(ws), f"{ws}/var/runs/r1/out/**", f"{ws}/var/runs/r1/tmp/**"]


def test_codex_profile_denies_privileged_tokens_not_the_worker_token(ws, home):
    fs = profile(ws)
    for role in ("owner", "orchestrator", "verifier"):
        assert fs[f"{ws}/var/secrets/{role}.token"] == "deny"
    assert f"{ws}/var/secrets/worker.token" not in fs           # the phase acts as worker


def test_codex_profile_protects_machinery_git_and_var(ws, home):
    fs = profile(ws)
    for d in ("bin", ".venv", "src", "catalog", "tests", ".claude", "var"):
        assert fs[f"{ws}/{d}/**"] == "read", d
    for f in ("konstant.toml", "install.sh", "pyproject.toml", "AGENTS.md"):
        assert fs[f"{ws}/{f}"] == "read", f
    assert fs[f"{ws}/projects/demo/.git/config"] == "read"
    assert fs[f"{ws}/projects/demo/.git/hooks/**"] == "read"


def test_codex_profile_names_only_existing_paths_once(ws, home):
    """bubblewrap cannot create a mount point inside a read-only tree (seen live on board.db-shm):
    nothing under var/ but the tokens and the phase dirs, and no path that does not exist."""
    (home / ".ssh").mkdir()
    fs = profile(ws)
    assert fs["~/.ssh"] == "deny" and "~/.aws" not in fs
    assert f"{ws}/var/board.db" not in fs and f"{ws}/var/secrets/**" not in fs
    assert f"{ws}/CLAUDE.md" not in fs                       # absent in this workspace


def test_codex_refuses_a_path_it_cannot_quote(tmp_path, home):
    bad = tmp_path / 'ws"x'
    (bad / "var" / "runs" / "r1").mkdir(parents=True)
    with pytest.raises(codex_mod.HarnessError, match="cannot be written"):
        codex_mod.inline_table(codex_mod.filesystem(Phase(values(bad))))


@pytest.mark.skipif(not shutil.which("codex"), reason="codex not installed")
def test_codex_sandbox_enforces_the_rendered_profile(ws, home):
    """The real Codex sandbox, no model: konstant's profile denies an outside write and a
    privileged token read and allows a write in the project (two-sided)."""
    import os
    outside = home / "outside"
    outside.mkdir()
    table = codex_mod.inline_table(profile(ws))
    proj = ws / "projects" / "demo"
    env = {**os.environ, "HOME": REAL_HOME}     # codex keeps its helpers in the real CODEX_HOME
    script = (f"echo x > {outside}/escape; echo rc1=$?; cat {ws}/var/secrets/owner.token; "
              f"echo rc2=$?; cat {ws}/var/secrets/worker.token >/dev/null; echo rc3=$?; "
              f"echo x > {proj}/inside; echo rc4=$?")
    r = subprocess.run(["codex", "sandbox", "-P", "konstant", "-C", str(proj), "-c",
                        f"permissions.konstant.filesystem={table}", "--", "bash", "-c", script],
                       capture_output=True, text=True, timeout=60, env=env)
    if "rc1=" not in r.stdout:
        pytest.skip(f"codex sandbox unusable here: {r.stderr[-300:]}")
    assert "rc1=1" in r.stdout and not (outside / "escape").exists()
    assert "rc2=1" in r.stdout and "rc3=0" in r.stdout
    assert "rc4=0" in r.stdout and (proj / "inside").is_file()


def gen(ws, name, **over):
    return Generator(CAT, ws, {"allow": ["Bash(npm test *)", "WebFetch"], "sandbox": True},
                     python="/py/bin/python", harness=hcfg(name=name, **over))


def test_dsh_patch_maps_the_reach(ws, home):
    rows = {r["id"]: r for r in yaml.safe_load(_strip_js(gen(ws, "dsh").render()[
        ".dsh/konstant.patch.yml"]))}
    assert rows["sandbox-policy"]["config"]["mode"] == "workspace-write"
    assert rows["approval"]["config"]["policy"] == "never"
    assert rows["permission"]["config"]["defaultPreset"] == "konstant"
    assert rows["permission"]["config"]["presets"]["konstant"] == {
        "sandbox": "workspace-write", "approval": "never"}
    assert rows["agent-instructions"]["config"]["projectRootMarkers"] == ["konstant.toml"]
    sk = rows["skill-filesystem"]["config"]
    assert sk["includeDefaultRoots"] is False and sk["customSkillDirs"] == [
        str(ws / ".agents" / "skills")]
    assert "llm-pi-ai" not in rows                     # no endpoint: no provider


def test_dsh_patch_endpoint_provider_lists_every_dsh_model(ws, home):
    text = gen(ws, "dsh", model="a1", endpoint={"base_url": "http://127.0.0.1:8000/v1",
                                                "api_key_env": "MYKEY"},
               types={"review": {"model": "b2"}, "docs": {"name": "codex", "model": "c3"}}
               ).render()[".dsh/konstant.patch.yml"]
    rows = {r["id"]: r for r in yaml.safe_load(_strip_js(text))}
    prov = rows["llm-pi-ai"]["config"]["providers"]["konstant"]
    assert prov["baseURL"] == "http://127.0.0.1:8000/v1" and prov["apiKeyEnv"] == "MYKEY"
    assert [m["id"] for m in prov["models"]] == ["a1", "b2"]
    assert rows["llm-deepseek"]["disabled"] is True
    assert 'model: !!js process.env.KONSTANT_MODEL || "a1"' in text


def _strip_js(text: str) -> str:
    return re.sub(r"!!js ", "", text)


def gemini_rules(ws, **over):
    text = gen(ws, "gemini", **over).render()[".gemini/konstant-policy.toml"]
    return _toml.loads(text)["rule"]


def test_gemini_policy_allows_konstant_verbs_git_and_the_test_runner(ws, home):
    rules = gemini_rules(ws)
    allow = {r["commandPrefix"] for r in rules if r["decision"] == "allow"}
    assert {"bin/konstant job", f"{ws}/bin/konstant task check", "git status",
            "npm test"} <= allow
    assert not any(p.startswith("git init") for p in allow)


def test_gemini_policy_denies_other_roles_and_machinery_edits(ws, home):
    rules = gemini_rules(ws)
    deny = [r for r in rules if r["decision"] == "deny"]
    prefixes = {r.get("commandPrefix") for r in deny}
    assert {"bin/konstant verify", "bin/konstant job verdict", "bin/konstant task run"} <= prefixes
    edit = next(r for r in deny if r["toolName"] == ["write_file", "replace"])
    pat = re.compile(edit["argsPattern"])
    for bad in ("catalog/x.md", "bin/konstant", "projects/demo/.git/config", "konstant.toml\"",
                "var/secrets/owner.token", "var/board.db", "var/runs/r1/record.json"):
        assert pat.search(f'"file_path":"{ws}/{bad}'), bad
    for good in ("projects/demo/app.py", "projects/demo/README.md", "var/runs/r1/out/DONE.md"):
        assert not pat.search(f'"file_path":"{ws}/{good}"'), good
    assert max(r["priority"] for r in rules if r["decision"] == "allow") < min(
        r["priority"] for r in deny)
    regex = next(r for r in deny if "commandRegex" in r)["commandRegex"]
    assert re.search(regex, "bin/konstant job list --as owner") and not re.search(
        regex, "bin/konstant job list")
