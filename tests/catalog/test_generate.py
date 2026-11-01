"""`konstant agents sync [--check]`: what it writes, drift detection both ways, stale removal, and
the generated surfaces parse ."""
from __future__ import annotations

import json
import re

import pytest
import yaml

from konstant import catalog
from konstant.agents.generate import HEADER, GenerateError, Generator
from tests.catalog.conftest import SRC


def gen(ws, root=SRC, perm=None):
    return Generator(catalog.load(root, check_files=True), ws, perm or {}, python="/py/bin/python")


def test_sync_then_check_is_clean(workspace):
    g = gen(workspace)
    changed = g.sync()
    assert len(changed) == len(g.render()) and g.check() == []
    assert len(list((workspace / ".claude" / "agents").iterdir())) == 12   # + planner, scenario-writer
    assert len(list((workspace / ".claude" / "skills").iterdir())) == 36   # + workflow-intake
    assert (workspace / "CLAUDE.md").is_file() and (workspace / "AGENTS.md").is_file()
    assert g.sync() == []                                          # idempotent


def test_check_names_an_edited_file_and_sync_restores_it(workspace):
    g = gen(workspace)
    g.sync()
    target = workspace / ".claude" / "skills" / "verify" / "SKILL.md"
    good = target.read_text()
    target.write_text(good + "\nlocal edit\n")
    assert g.check() == ["drifted: .claude/skills/verify/SKILL.md"]
    (workspace / ".claude" / "agents" / "coder.md").unlink()
    assert "missing: .claude/agents/coder.md" in g.check()
    g.sync()
    assert target.read_text() == good and g.check() == []


def test_stale_generated_files_are_reported_and_removed(workspace):
    g = gen(workspace)
    g.sync()
    stale = workspace / ".claude" / "skills" / "old-skill"
    stale.mkdir()
    (stale / "SKILL.md").write_text(f"---\nname: old-skill\ndescription: x\n---\n{HEADER}\n")
    mine = workspace / ".claude" / "skills" / "my-own"                 # not generated: kept
    mine.mkdir()
    (mine / "SKILL.md").write_text("---\nname: my-own\ndescription: mine\n---\nbody\n")
    assert g.check() == ["stale: .claude/skills/old-skill/SKILL.md"]
    assert "removed: .claude/skills/old-skill/SKILL.md" in g.sync()
    assert not stale.exists() and mine.is_dir() and g.check() == []


def _front(text):
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    assert m, text[:80]
    return yaml.safe_load(m.group(1)), text[m.end():]


def test_every_generated_skill_and_agent_parses(workspace):
    gen(workspace).sync()
    skills = sorted((workspace / ".claude" / "skills").glob("*/SKILL.md"))
    assert len(skills) == 36
    for f in skills:
        meta, body = _front(f.read_text())
        assert meta["name"] == f.parent.name and isinstance(meta["description"], str) \
            and meta["description"].strip(), f
        assert body.startswith(HEADER), f
    for f in sorted((workspace / ".claude" / "agents").glob("*.md")):
        meta, body = _front(f.read_text())
        assert meta["name"] == f.stem and meta["description"], f
        assert body.startswith(HEADER) and "## Deliverable contract" in body \
            and "## Shared doctrine" in body, f
    wf = (workspace / ".claude" / "skills" / "workflow-code" / "SKILL.md").read_text()
    assert "| 3 | tester | - | TEST-verdict.md |" in wf and "ARCH-verdict.md" in wf
    assert (workspace / ".claude/skills/coding-discipline/scripts/dead_code.py").is_file()


def test_agent_profile_composes_its_contract_and_skills(workspace):
    g = gen(workspace)
    coder, tester = g.agent_prompt("coder"), g.agent_prompt("tester")
    assert "**BUILD**" in coder and "`coding-discipline`:" in coder
    assert "**VERDICT**" in tester and "`test-design`:" in tester
    assert "`board`:" in g.agent_prompt("orchestrator")
    assert not coder.startswith("---")                              # a phase prompt, no frontmatter


def test_claude_md_routing_table_comes_from_types_yaml(workspace):
    gen(workspace).sync()
    text = (workspace / "CLAUDE.md").read_text()
    assert text.startswith(HEADER)
    for t, a in (("code", "coder"), ("docs", "writer"), ("design", "architect")):
        assert f"| `{t}` | `{a}` |" in text
    assert str(workspace) in text and "# Orchestrator" in text


def test_a_broken_catalog_file_stops_the_render(workspace, cat_copy):
    f = cat_copy / "skills" / "spike" / "SKILL.md"
    f.write_text(f.read_text().replace("name: spike", "name: spiky"))
    with pytest.raises(GenerateError, match="skills/spike/SKILL.md"):
        gen(workspace, cat_copy).render()
    (cat_copy / "templates" / "agent.md.tmpl").write_text("{{nope}}\n")
    with pytest.raises(GenerateError, match="unknown placeholder"):
        gen(workspace, cat_copy).agent_prompt("coder")


def test_runner_uses_the_composed_profile(workspace):
    from konstant.gate.runner import PhaseRunner
    cat = catalog.load(SRC, check_files=True)
    rec = {"out": str(workspace / "out"), "workspace": str(workspace), "project": None}
    text = PhaseRunner(rec, cat, harness=None, run_dir=workspace).profile("reviewer")
    assert text.startswith("# Reviewer") and "## Shared doctrine" in text


def test_settings_json_is_valid_and_workspace_scoped(workspace):
    gen(workspace, perm={"allow": ["Bash(npm test *)"], "sandbox": True}).sync()
    data = json.loads((workspace / ".claude" / "settings.json").read_text())
    assert set(data) == {"$schema", "permissions", "sandbox"}
    ws = "//" + str(workspace).lstrip("/")
    p = data["permissions"]
    assert f"Edit({ws}/**)" in p["allow"] and "Bash(npm test *)" in p["allow"]
    assert not any(r.startswith(("Edit(", "Read(")) and not r.startswith(f"{r[:5]}{ws}/")
                   for r in p["allow"])
    assert f"Read({ws}/var/secrets/**)" in p["deny"] and f"Edit({ws}/bin/**)" in p["deny"]
    assert "Bash(bin/konstant verify *)" in p["deny"] and "Bash(bin/konstant job verdict *)" \
        in p["deny"] and "Bash(bin/konstant task run *)" in p["deny"]
    assert p["blockReadsOutsideWorkingDirectories"] is True
    assert p["disableBypassPermissionsMode"] == "disable"
    sb = data["sandbox"]
    assert sb["enabled"] and sb["allowUnsandboxedCommands"] is False
    assert sb["filesystem"]["allowWrite"] == [str(workspace)]
    assert str(workspace / "var" / "secrets") in sb["filesystem"]["denyRead"]


def test_sandbox_can_be_switched_off(workspace):
    gen(workspace, perm={"allow": [], "sandbox": False}).sync()
    data = json.loads((workspace / ".claude" / "settings.json").read_text())
    assert "sandbox" not in data and data["permissions"]["deny"]


@pytest.mark.parametrize("rule,needle", [
    ("Bash", "whole tool"),
    ("Bash(*)", "whole tool"),
    ("Edit", "whole tool"),
    ("Read(//etc/**)", "outside the workspace"),
    ("Edit(~/.ssh/**)", "outside the workspace"),
    ("Edit(./../x/**)", "outside the workspace"),
    ("Bash(* --version)", "wildcard before the command"),
    ("not a rule", "not a Tool"),
])
def test_a_widening_permissions_rule_is_refused(workspace, rule, needle):
    with pytest.raises(GenerateError, match=needle):
        gen(workspace, perm={"allow": [rule]}).render()


def test_a_scoped_permissions_rule_is_accepted(workspace):
    ws = "//" + str(workspace).lstrip("/")
    out = gen(workspace, perm={"allow": ["Bash(npm test *)", f"Edit({ws}/projects/**)",
                                         "Read(./docs/**)", "WebFetch"]}).render()
    assert "Bash(npm test *)" in out[".claude/settings.json"]
