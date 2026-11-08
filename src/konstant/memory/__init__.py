"""Built-in memory (wave L5-M; DESIGN §7.4, docs/CONCEPTS.md "Memory").

The VAULT (`memory/` in the workspace) is the source of truth: plain Markdown notes with YAML
frontmatter, Obsidian-compatible (`[[wikilinks]]`, `#tags`, `tags:` in the frontmatter), in two
pools (`shared/`: every producer reads and writes it; `sealed/`: the scenario writer's and the
verifier's notes, which no producer reads) with one folder per writer inside, versioned in its
OWN git repository
(`memory/.git`, never the workspace's or a project's). Every write konstant makes is one commit,
authored by the identity that wrote it, and one row of the board's append-only `memory_writes`.

The INDEX (`var/memory/index.db`) is a cache: SQLite FTS5 (Python's standard library) for
lexical recall, plus optional vectors from a local OpenAI-compatible embedding endpoint
(`[memory] embed_endpoint` / `embed_model`); it is rebuilt from the vault at any time
(`konstant memory reindex`). Without an endpoint recall is lexical and says so.

Every harness reaches memory through ONE MCP server, `konstant mcp memory` (tools kb_recall,
kb_store, kb_note), or its CLI fallback `konstant memory recall|store|note`. Both go through the
board, which knows the caller's identity from its token and enforces the integrity rules
(guard.py): one shared pool every producer learns from, a sealed pool behind one-way glass
(the scenario writer and the verifier read the shared pool, write only the sealed one), each
note labelled with its source job and whether that job reached `verified`, a store-time scan
that refuses anything from the sealed holdout store,
attribution of every write. No phase reads the vault's files directly (machinery.SEALED), and the
verifier never treats memory as evidence.

  note.py     the note format (frontmatter, wikilinks, tags, file names)
  vault.py    the vault on disk and its git commits (plumbing, pinned environment: F-04)
  index.py    the recall index (SQLite FTS5, optional vectors, rebuild)
  embed.py    the local OpenAI-compatible embedding client (urllib)
  guard.py    the pools, the store-time holdout scan
  view.py     the scenario writer's read-only copy (it holds no token)
  service.py  the operations the board routes call
  mcp.py      the stdio MCP server
"""
