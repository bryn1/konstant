"""The vault (Obsidian-compatible notes, its own git repo) and the rebuildable recall index."""
from __future__ import annotations

import subprocess

import pytest

from konstant.memory import note as note_mod
from konstant.memory.index import Index
from konstant.memory.vault import Vault, VaultError, safe_rel


def test_note_parses_frontmatter_wikilinks_and_tags():
    text = ("---\ntitle: Board ports\ntags: [ops, board]\nactor: worker\n---\n"
            "See [[Install notes|install]] and [[Other#Heading]]. #deploy `#notatag`\n")
    n = note_mod.parse(text, "worker/Board ports.md")
    assert n.title == "Board ports" and n.namespace == "worker" and n.actor == "worker"
    assert n.links == ["Install notes", "Other"]
    assert n.tags == ["ops", "board", "deploy"]


def test_note_without_frontmatter_is_all_body_and_named_by_file():
    n = note_mod.parse("just text #idea\n", "notes/My idea.md")
    assert n.title == "My idea" and n.meta == {} and n.tags == ["idea"]
    bad = note_mod.parse("---\n: : [\n---\nbody\n", "x.md")
    assert bad.meta == {} and "body" in bad.body


def test_render_round_trips_and_file_titles_are_safe():
    text = note_mod.render({"title": "A/B: c?", "tags": ["x"]}, "body [[L]]")
    n = note_mod.parse(text, "worker/x.md")
    assert n.title == "A/B: c?" and n.links == ["L"] and n.tags == ["x"]
    assert note_mod.file_title("../../etc/passwd") == "etc passwd"
    assert note_mod.file_title("...") == "note"
    for bad in ("../x.md", "a/.git/x.md", "/abs.md", "a/b.txt", ".hidden.md"):
        with pytest.raises(VaultError):
            safe_rel(bad)


def git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True).stdout


def test_every_write_is_one_commit_of_that_file_only_authored_by_the_writer(tmp_path):
    v = Vault(tmp_path / "memory")
    c1 = v.write("worker/a.md", "---\ntitle: a\n---\none\n", "worker", "note a")
    # the owner stages something of his own in the vault: konstant's next commit leaves it out
    (v.root / "notes").mkdir()
    (v.root / "notes" / "mine.md").write_text("private draft\n")
    subprocess.run(["git", "-C", str(v.root), "add", "notes/mine.md"], check=True)
    c2 = v.write("planner/b.md", "two\n", "planner", "note b")
    assert c1 != c2 and v.head() == c2
    assert git(v.root, "show", "--name-only", "--format=%an", c2).split() == \
        ["konstant", "planner", "planner/b.md"]
    assert "notes/mine.md" not in git(v.root, "ls-tree", "-r", "--name-only", c2)
    assert [s for _c, _a, s in v.log()] == ["note b", "note a"]
    assert (v.root / ".git" / "hooks").exists() is False      # no template, no hooks


def test_vault_never_writes_through_a_symlink(tmp_path):
    v = Vault(tmp_path / "memory")
    v.ensure()
    (v.root / "worker").mkdir()
    (v.root / "worker" / "x.md").symlink_to(tmp_path / "outside.md")
    with pytest.raises(VaultError):
        v.write("worker/x.md", "x", "worker", "m")
    assert not (tmp_path / "outside.md").exists()


def _vault_with_notes(tmp_path):
    v = Vault(tmp_path / "memory")
    v.write("worker/Ports.md", "---\ntitle: Ports\n---\nThe board port 8470 clashes with a "
            "proxy.\n", "worker", "m")
    v.write("planner/Plan.md", "---\ntitle: Plan\n---\nSplit the greeter into two jobs.\n",
            "planner", "m")
    return v


def test_index_sync_search_and_rebuild_from_the_vault(tmp_path):
    v = _vault_with_notes(tmp_path)
    idx = Index(tmp_path / "var" / "memory" / "index.db", v)
    stats = idx.sync({})
    assert stats["indexed"] == 2
    hits, mode = idx.search("board port", attributed_only=False)
    assert mode == "lexical" and hits[0]["path"] == "worker/Ports.md"
    assert "[port]" in hits[0]["snippet"].lower() or "[board]" in hits[0]["snippet"].lower()
    hits, _ = idx.search("greeter", pools={"sealed"}, attributed_only=False)
    assert hits == []                                    # the pool filter applies in SQL
    # the index is a cache: delete it, rebuild from the vault, same answers
    (tmp_path / "var" / "memory" / "index.db").unlink()
    assert idx.rebuild({})["indexed"] == 2
    assert idx.search("greeter", attributed_only=False)[0][0]["path"] == "planner/Plan.md"


def test_index_follows_hand_edits_and_deletions(tmp_path):
    v = _vault_with_notes(tmp_path)
    idx = Index(tmp_path / "idx.db", v)
    idx.sync({})
    (v.root / "worker" / "Ports.md").write_text("now about kittens\n")
    (v.root / "planner" / "Plan.md").unlink()
    stats = idx.sync({})
    assert stats["indexed"] == 1 and stats["removed"] == 1
    assert idx.search("kittens", attributed_only=False)[0][0]["path"] == "worker/Ports.md"
    assert idx.search("greeter", attributed_only=False)[0] == []


def test_attribution_is_the_hash_of_konstants_own_write(tmp_path):
    v = _vault_with_notes(tmp_path)
    idx = Index(tmp_path / "idx.db", v)
    sha = note_mod.sha256((v.root / "worker" / "Ports.md").read_text())
    idx.sync({"worker/Ports.md": sha})
    assert [h["path"] for h in idx.search("port", attributed_only=True)[0]] == ["worker/Ports.md"]
    (v.root / "worker" / "Ports.md").write_text("---\ntitle: Ports\n---\nport changed by hand\n")
    idx.sync({"worker/Ports.md": sha})
    assert idx.search("port", attributed_only=True)[0] == []      # no longer konstant's write
    assert idx.search("port", attributed_only=False)[0] != []


def test_fts_query_syntax_in_a_query_is_data(tmp_path):
    v = _vault_with_notes(tmp_path)
    idx = Index(tmp_path / "idx.db", v)
    idx.sync({})
    for q in ('"', "port OR", "NEAR(port", "*", "title:board", "a\"b"):
        hits, _ = idx.search(q, attributed_only=False)
        assert isinstance(hits, list)
