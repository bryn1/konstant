"""The shipped catalog: one agent per type, every reference resolves, and the planted-bad copies
go red with the missing file named."""
from __future__ import annotations

import re

import pytest
import yaml

from konstant import catalog
from tests.catalog.conftest import SRC

TYPES = {"code": "coder", "frontend": "frontend", "infra": "infra", "test": "tester",
         "security": "security", "review": "reviewer", "research": "researcher",
         "docs": "writer", "design": "architect"}


def test_one_agent_per_type():
    cat = catalog.load(SRC, check_files=True)
    mapping = {t: cat.agent_of(t) for t in cat.type_names()}
    assert mapping == TYPES
    assert len(set(mapping.values())) == len(mapping) == 9          # a bijection
    assert {cat.type_of_agent(a) for a in mapping.values()} == set(TYPES)
    assert cat.type_of_agent("orchestrator") is None
    files = sorted(p.stem for p in (SRC / "agents").glob("*.md"))
    assert files == sorted(list(TYPES.values()) + ["orchestrator"]) and len(files) == 10


def test_counts_skills_and_workflows():
    cat = catalog.load(SRC, check_files=True)
    skills = sorted(p.name for p in (SRC / "skills").iterdir() if (p / "SKILL.md").is_file())
    assert len(skills) == 26
    assert sorted(cat.skill_names()) == skills                     # no orphan, none missing
    workflows = sorted(p.stem for p in (SRC / "workflows").glob("*.md"))
    assert workflows == sorted(TYPES) and [cat.workflow_of(t) for t in TYPES] == list(TYPES)


def test_every_skill_named_in_types_yaml_exists_red(cat_copy):
    data = yaml.safe_load((cat_copy / "types.yaml").read_text())
    data["types"]["code"]["skills"].append("ghost-skill")
    (cat_copy / "types.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    catalog.load(cat_copy)                                         # structure alone is fine
    with pytest.raises(catalog.CatalogError, match="skills/ghost-skill/SKILL.md"):
        catalog.load(cat_copy, check_files=True)


def test_every_skill_named_in_types_yaml_exists_green(cat_copy):
    assert catalog.load(cat_copy, check_files=True).skill_names()


def test_every_phase_agent_exists_red(cat_copy):
    (cat_copy / "agents" / "tester.md").unlink()
    with pytest.raises(catalog.CatalogError, match="agents/tester.md"):
        catalog.load(cat_copy, check_files=True)


def test_every_workflow_exists_red(cat_copy):
    (cat_copy / "workflows" / "design.md").unlink()
    with pytest.raises(catalog.CatalogError, match="workflows/design.md"):
        catalog.load(cat_copy, check_files=True)


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["types"]["code"].pop("workflow"), "needs a workflow"),
    (lambda d: d["types"]["code"].update(workflow="Code Flow"), "needs a workflow"),
    (lambda d: d["types"]["code"].pop("skills"), "skills must be a list"),
    (lambda d: d["types"]["code"].update(skills=["Not_Kebab"]), "skills must be a list"),
    (lambda d: d["types"]["code"].update(skills=["verify", "verify"]), "twice"),
    (lambda d: d.update(roles={"janitor": {"skills": []}}), "role agents"),
    (lambda d: d["roles"]["orchestrator"].update(skills="board"), "roles.orchestrator skills"),
])
def test_content_keys_are_validated(cat_copy, mutate, needle):
    data = yaml.safe_load((cat_copy / "types.yaml").read_text())
    mutate(data)
    (cat_copy / "types.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(catalog.CatalogError, match=needle):
        catalog.load(cat_copy)


def _front(path):
    m = re.match(r"\A---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path}: no frontmatter"
    return yaml.safe_load(m.group(1))


def test_catalog_skill_files_are_distilled_and_well_formed():
    total = 0
    for d in sorted((SRC / "skills").iterdir()):
        f = d / "SKILL.md"
        meta = _front(f)
        assert meta["name"] == d.name and len(meta["description"]) >= 60, f
        assert "<" not in meta["description"] and ">" not in meta["description"], f
        n = len(f.read_text().splitlines())
        assert n <= 200, f"{f}: {n} lines"                          # per-file bound
        total += n
    assert total <= 2612       # the catalog's total size budget


def test_agent_sources_have_frontmatter():
    for f in sorted((SRC / "agents").glob("*.md")):
        meta = _front(f)
        assert meta["name"] == f.stem and meta["description"], f
        if f.stem != "orchestrator":
            assert "Skill" in meta["tools"], f"{f}: an agent with tools must be able to load skills"


IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
HOMEPATH = re.compile(r"/(?:home|srv|Users)/\w")


def identifier_hits(root):
    bad = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            ips = [i for i in IP.findall(line) if not i.startswith(("127.", "0.0.0.0"))]
            if ips or EMAIL.search(line) or HOMEPATH.search(line):
                bad.append(f"{f.relative_to(root)}:{n}: {line.strip()[:80]}")
    return bad


def test_catalog_carries_no_host_or_person_identifiers():
    bad = identifier_hits(SRC)
    assert not bad, "\n".join(bad)


def test_identifier_scan_goes_red(tmp_path):
    ip, mail = ".".join(["10", "1", "2", "3"]), "someone" + "@" + "realmail.com"   # not literals
    (tmp_path / "x.md").write_text(f"ssh to {ip}\nmail {mail}\nsee /home/bob/x\n")
    (tmp_path / "ok.md").write_text("bind 127.0.0.1 and 0.0.0.0 only\n")
    assert [h.split(":")[1] for h in identifier_hits(tmp_path)] == ["1", "2", "3"]
