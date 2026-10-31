"""`agents sync` per harness: only the configured harnesses' surfaces, golden files for the
adapter-specific ones, stale removal when the harness changes, `--check --harness`."""
from __future__ import annotations

import json

from konstant import catalog
from konstant.agents.generate import HEADER, Generator
from konstant.harnesses.gemini import settings_json
from tests.harness.conftest import golden, hcfg, norm

CAT = catalog.load()
PERM = {"allow": ["Bash(pytest *)", "Bash(npm test *)"], "sandbox": True}


def gen(ws, **h):
    return Generator(CAT, ws, PERM, python="/py/bin/python", harness=hcfg(**h))


def test_claude_only_by_default(ws, home):
    files = gen(ws).render()
    assert ".claude/settings.json" in files and "CLAUDE.md" in files and "AGENTS.md" in files
    assert not any(p.startswith((".agents/", ".dsh/", ".gemini/")) for p in files)


def test_codex_gets_agents_md_and_shared_skills_only(ws, home):
    files = gen(ws, name="codex").render()
    assert "AGENTS.md" in files and not any(p.startswith(".claude/") for p in files)
    assert "CLAUDE.md" not in files
    skills = {p.split("/")[2] for p in files if p.startswith(".agents/skills/")}
    assert {"verify", "workflow-code"} <= skills
    md = files["AGENTS.md"]
    assert ".agents/skills/<name>/SKILL.md" in md and "is `.claude/agents/<agent>.md`" not in md


def test_shared_skill_equals_the_claude_copy(ws, home):
    a = gen(ws, name="codex").render()[".agents/skills/verify/SKILL.md"]
    c = gen(ws).render()[".claude/skills/verify/SKILL.md"]
    assert a == c and HEADER in a and a.startswith("---\nname: verify\n")


def test_adapter_surfaces_are_golden(ws, home):
    files = gen(ws, name="dsh", model="local-model", types={"review": {"name": "gemini"}},
                endpoint={"base_url": "http://127.0.0.1:8000/v1", "api_key_env": ""}).render()
    for rel, gname in ((".dsh/konstant.patch.yml", "dsh-konstant.patch.yml"),
                       (".gemini/settings.json", "gemini-settings.json"),
                       (".gemini/konstant-policy.toml", "gemini-konstant-policy.toml")):
        golden(gname, norm(files[rel], ws))
    golden("agents-md-no-claude.md", norm(files["AGENTS.md"], ws))


def test_union_of_default_and_overrides(ws, home):
    g = gen(ws, name="claude", types={"review": {"name": "dsh"}, "docs": {"name": "codex"}})
    assert g.harness_names() == ["claude", "dsh", "codex"]
    files = g.render()
    assert {".claude/settings.json", ".dsh/konstant.patch.yml",
            ".agents/skills/verify/SKILL.md"} <= set(files)


def test_switching_harness_removes_the_old_surfaces_but_not_user_files(ws, home):
    g = gen(ws)
    g.sync()
    (ws / ".claude" / "mine.json").write_text("{}")             # the user's own file
    g2 = gen(ws, name="codex")
    stale = [ln for ln in g2.check() if ln.startswith("stale:")]
    assert "stale: CLAUDE.md" in stale and "stale: .claude/settings.json" in stale
    g2.sync()
    assert not (ws / "CLAUDE.md").exists() and not (ws / ".claude" / "agents").exists()
    assert (ws / ".claude" / "mine.json").is_file() and g2.check() == []


def test_a_user_gemini_settings_file_is_never_taken_over(ws, home):
    (ws / ".gemini").mkdir()
    (ws / ".gemini" / "settings.json").write_text('{"theme": "mine"}\n')
    g = gen(ws, name="codex")
    g.sync()
    assert (ws / ".gemini" / "settings.json").read_text() == '{"theme": "mine"}\n'
    (ws / ".gemini" / "settings.json").write_text(settings_json())     # exactly ours: stale
    assert "stale: .gemini/settings.json" in g.check()


def test_check_per_harness_names_only_its_drift(ws, home):
    g = gen(ws, name="claude", types={"review": {"name": "gemini"}})
    g.sync()
    (ws / ".gemini" / "konstant-policy.toml").write_text(HEADER + "\nedited\n")
    assert g.check("gemini") == ["drifted: .gemini/konstant-policy.toml"]
    assert g.check("claude") == []
    assert g.check() == ["drifted: .gemini/konstant-policy.toml"]


def test_cli_check_reports_per_harness(tmp_path, home):
    from tests.cli.conftest import Workspace
    (tmp_path / "w").mkdir()
    w = Workspace(tmp_path / "w")
    toml = w.home / "konstant.toml"
    toml.write_text(toml.read_text() + '[harness]\nname = "dsh"\n[harness.types.review]\n'
                    'name = "codex"\n')
    w.ok("agents", "sync")
    res = w.run("--json", "agents", "sync", "--check")
    data = json.loads(res.stdout)
    assert res.returncode == 0 and data["harnesses"] == {"dsh": [], "codex": []}
    (w.home / ".dsh" / "konstant.patch.yml").write_text(HEADER + "\n")
    res = w.run("agents", "sync", "--check", "--harness", "dsh")
    assert res.returncode == 1 and "drifted: .dsh/konstant.patch.yml" in res.stdout
    res = w.run("agents", "sync", "--check", "--harness", "codex")
    assert res.returncode == 0, res.stdout
    res = w.run("agents", "sync", "--harness", "gemini")
    assert res.returncode == 1 and "not configured" in res.stdout
