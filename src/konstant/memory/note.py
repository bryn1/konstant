"""The note format: Obsidian-compatible Markdown with YAML frontmatter.

    ---
    title: Board port conflicts
    tags: [ops, board]
    actor: worker
    kind: note
    created: 2026-11-02T10:00:00Z
    updated: 2026-11-02T10:00:00Z
    ---
    The board refuses a port another process holds; see [[Install notes]]. #ops

A note's file name is its title (Obsidian resolves `[[Title]]` to `Title.md`), made safe for
every file system; its pool is the vault's top folder (memory/guard.py). Tags come from the
frontmatter
`tags:` list and from inline `#tags`; links from `[[wikilinks]]` (alias and heading parts
dropped). Parsing never fails on a hand-written note: bad frontmatter is treated as body.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import yaml

_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
WIKILINK = re.compile(r"\[\[([^\[\]|#\n]+)(?:#[^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\]")
TAG = re.compile(r"(?<![\w/#&\[])#([A-Za-z][\w/-]{0,63})")
_UNSAFE = re.compile(r"[^A-Za-z0-9 ._()+,-]+")
TITLE_MAX = 80


@dataclass
class Note:
    path: str                       # vault-relative, posix, ends in .md
    namespace: str
    title: str
    body: str
    meta: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)
    links: list = field(default_factory=list)
    sha256: str = ""

    @property
    def actor(self) -> str:
        return str(self.meta.get("actor") or "")

    @property
    def kind(self) -> str:
        return str(self.meta.get("kind") or "note")

    @property
    def updated(self) -> str:
        return str(self.meta.get("updated") or self.meta.get("created") or "")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split(text: str) -> tuple:
    """(frontmatter dict, body). A note without valid frontmatter is all body."""
    m = _FRONT.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, text[m.end():]


def _tag_list(raw) -> list:
    if isinstance(raw, str):
        raw = re.split(r"[,\s]+", raw)
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(t).lstrip("#") for t in raw if str(t).strip().lstrip("#")]


def links(body: str) -> list:
    return list(dict.fromkeys(m.group(1).strip() for m in WIKILINK.finditer(body)))


def tags(meta: dict, body: str) -> list:
    inline = [m.group(1) for m in TAG.finditer(_strip_code(body))]
    return list(dict.fromkeys(_tag_list(meta.get("tags")) + inline))


def _strip_code(body: str) -> str:
    return re.sub(r"```.*?```|`[^`\n]*`", " ", body, flags=re.S)


def parse(text: str, path: str) -> Note:
    meta, body = split(text)
    namespace = path.split("/", 1)[0] if "/" in path else ""
    stem = path.rsplit("/", 1)[-1]
    stem = stem[:-3] if stem.endswith(".md") else stem
    title = str(meta.get("title") or stem)
    return Note(path=path, namespace=namespace, title=title, body=body, meta=meta,
                tags=tags(meta, body), links=links(body), sha256=sha256(text))


def render(meta: dict, body: str) -> str:
    """Frontmatter (insertion order kept) + body, ending in one newline."""
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=None,
                           width=1000).strip()
    return f"---\n{front}\n---\n{body.strip()}\n"


def file_title(title: str) -> str:
    """A title as a file name stem: unsafe characters become a space, at most TITLE_MAX chars,
    never empty, never hidden (no leading dot)."""
    t = re.sub(r"\.{2,}", " ", _UNSAFE.sub(" ", title))
    t = re.sub(r"\s+", " ", t).strip(" .")[:TITLE_MAX].strip(" .")
    return t or "note"


def title_from(text: str, words: int = 8) -> str:
    """A short title for a fact stored without one: its first words."""
    first = re.sub(r"\s+", " ", text.strip().splitlines()[0] if text.strip() else "")
    return " ".join(first.split(" ")[:words])[:TITLE_MAX] or "fact"
