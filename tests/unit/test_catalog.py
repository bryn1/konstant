"""catalog/types.yaml: the shipped stub loads; every invariant has a planted-bad case."""
from __future__ import annotations

import copy

import pytest
import yaml

from konstant import catalog

EXPECTED = {"code": "coder", "frontend": "frontend", "infra": "infra", "test": "tester",
            "security": "security", "review": "reviewer", "research": "researcher",
            "docs": "writer", "design": "architect", "intake": "planner"}


def test_the_shipped_catalog_has_nine_types_one_agent_each():
    """Nine task types plus the flag-only level-5 `intake` (agent planner, LEVEL5 4.2); the role
    agents are the orchestrator and the scenario writer (LEVEL5 3.4)."""
    cat = catalog.load()
    assert {t: cat.agent_of(t) for t in cat.type_names()} == EXPECTED
    assert len(set(EXPECTED.values())) == 10                      # a bijection
    assert cat.review_types == ["review", "docs", "design", "research"]
    assert [t for t in cat.type_names() if cat.flag_only(t)] == ["intake"]
    assert "orchestrator" in cat.agents() and "scenario-writer" in cat.agents()
    assert len(cat.agents()) == 12


def _write(tmp_path, data):
    (tmp_path / "types.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    return tmp_path


@pytest.fixture()
def good():
    return yaml.safe_load((catalog._source_root() / "types.yaml").read_text())


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["types"]["docs"].update(agent="coder"), "agent of both"),
    (lambda d: d["types"]["docs"].update(agent="orchestrator"), "is a role"),
    (lambda d: d["types"]["docs"].pop("agent"), "exactly one agent"),
    (lambda d: d["types"]["docs"].update(agent=["writer", "coder"]), "exactly one agent"),
    (lambda d: d["types"].update(project=dict(d["types"]["docs"], agent="x")), "reserved"),
    (lambda d: d["types"]["docs"].update(deliverable="essay"), "deliverable"),
    (lambda d: d["types"]["docs"].update(summary=""), "summary"),
    (lambda d: d.update(review_types=["docs", "poetry"]), "review_types"),
    (lambda d: d.update(version="1"), "version"),
    (lambda d: d.update(types={}), "non-empty"),
])
def test_invariants_are_enforced(tmp_path, good, mutate, needle):
    data = copy.deepcopy(good)
    mutate(data)
    with pytest.raises(catalog.CatalogError, match=needle):
        catalog.load(_write(tmp_path, data))


def test_good_copy_loads(tmp_path, good):
    assert sorted(catalog.load(_write(tmp_path, good)).type_names()) == sorted(EXPECTED)


def test_classifier_order_puts_code_last():
    """The classifier tries types in file order: specific first, `code` the catch-all last."""
    names = catalog.load().type_names()
    assert names[-1] == "code" and names[0] == "security"


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["types"]["code"].update(keywords="(unclosed"), "not a valid regex"),
    (lambda d: d["types"]["code"].pop("keywords"), "keywords must be"),
    (lambda d: d["types"]["code"].update(phases=[]), "non-empty phases"),
    (lambda d: d["types"]["code"]["phases"][2].update(agent="ghost"), "not the agent of any type"),
    (lambda d: d["types"]["code"]["phases"][0].update(step="middle"), "step must be"),
    (lambda d: d["types"]["code"]["phases"][0].update(when="sometimes"), "when must be"),
    (lambda d: d["types"]["code"]["phases"][2].update(verdict="test.md"), "verdict must look"),
    (lambda d: d["types"]["code"]["phases"][3].update(verdict="TEST-verdict.md"), "used twice"),
    (lambda d: d["types"]["code"]["phases"][1].update(colour="red"), "unknown key"),
    (lambda d: d["types"]["code"]["phases"].pop(1), "no producer phase"),
    (lambda d: d["types"]["code"].update(read_only="no"), "read_only must be"),
    (lambda d: d.update(surfaces=[]), "surfaces"),
    (lambda d: d.update(verdict_words={"pass": ["PASS"]}), "verdict_words"),
    (lambda d: d.update(small_shapes=["(x"]), "small_shapes"),
    (lambda d: d.pop("deliverable_signal"), "deliverable_signal"),
])
def test_gate_vocabulary_invariants(tmp_path, good, mutate, needle):
    data = copy.deepcopy(good)
    mutate(data)
    with pytest.raises(catalog.CatalogError, match=needle):
        catalog.load(_write(tmp_path, data))


def test_phase_accessors():
    cat = catalog.load()
    assert [p["agent"] for p in cat.phases("code")] == \
        ["architect", "coder", "tester", "reviewer", "architect"]
    assert [p["verdict"] for p in cat.verifying("code")] == \
        ["TEST-verdict.md", "REVIEW-verdict.md", "ARCH-verdict.md"]
    assert [p["agent"] for p in cat.phases("code") if cat.is_producer("code", p)] == ["coder"]
    assert [p["agent"] for p in cat.phases("test") if cat.is_producer("test", p)] == ["tester"]
    assert [p["agent"] for p in cat.phases("review") if cat.is_producer("review", p)] == \
        ["reviewer", "security"]
    assert cat.read_only("security") and not cat.read_only("code")
    assert cat.done_rows("code") and not cat.done_rows("docs")


def test_check_files_requires_agent_profiles(tmp_path):
    import shutil
    root = tmp_path / "catalog"
    shutil.copytree(catalog._source_root(), root)
    assert catalog.load(root, check_files=True)
    (root / "agents" / "coder.md").unlink()
    with pytest.raises(catalog.CatalogError, match="agents/coder.md"):
        catalog.load(root, check_files=True)


def test_find_root_order(tmp_path, monkeypatch, good):
    monkeypatch.delenv("KONSTANT_CATALOG", raising=False)
    assert catalog.find_root(tmp_path) == catalog._source_root().resolve()
    (tmp_path / "catalog").mkdir()
    _write(tmp_path / "catalog", good)
    assert catalog.find_root(tmp_path) == (tmp_path / "catalog").resolve()
    other = tmp_path / "elsewhere"
    other.mkdir()
    _write(other, good)
    monkeypatch.setenv("KONSTANT_CATALOG", str(other))
    assert catalog.find_root(tmp_path) == other.resolve()
    assert catalog.find_root(tmp_path, configured=str(tmp_path / "catalog")) == \
        (tmp_path / "catalog").resolve()


def test_malformed_yaml(tmp_path):
    (tmp_path / "types.yaml").write_text("types: [unclosed")
    with pytest.raises(catalog.CatalogError):
        catalog.load(tmp_path)
