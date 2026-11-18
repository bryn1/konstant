---
name: vault-indexing
description: How to index a directory of documents into a searchable knowledge store - read each file, extract key facts, store with metadata, verify recall works. Use when making a directory of documents searchable via a knowledge base or vector store.
---

# Vault indexing — making a document directory searchable

Use this skill when you need to make a set of documents (notes, ADRs, runbooks, research files)
searchable via a knowledge store or vector database.

## The procedure

1. **Enumerate the directory.** List the files you are indexing. Record the total count.

2. **For each document:**
   - Read the file
   - Extract the key facts: what does this document state, what decisions or facts does it
     record, what are the searchable concepts?
   - Store an entry in the knowledge store with:
     - The key fact or summary
     - The source path (so a recall hit can point back to the original)
     - Any relevant tags or metadata

3. **Verify recall works.** After indexing, run 2-3 queries that should return documents you
   just indexed. If a query returns nothing, the indexing is incomplete or the query terms
   do not match the stored vocabulary.

4. **Record the index run.** Note the directory path, the number of files indexed, and the
   date. If you re-index later, you can compare counts to detect additions or deletions.

## What makes a good index entry

- **Specific enough to retrieve.** A generic entry like "this is a document about security"
  retrieves on "security" but competes with everything else tagged security. Include the
  specific decision or fact.
- **Source-linked.** Every entry points to the file path or document ID so a hit leads back to
  the full content.
- **De-duplicated.** Check whether the fact is already stored before adding it. Duplicate entries
  degrade recall quality.

## Anti-patterns

- **Indexing file names, not content.** A file named `adr-0012-database-choice.md` says nothing
  without its content. Index the decision, not the filename.
- **Over-indexing.** Not every sentence needs to be an index entry. Index the claims that people
  would search for.
- **Indexing without verifying.** Run at least one query after indexing. A store that returns
  nothing on a known topic has an indexing problem.
- **Not recording the index run.** Without a record, the next session cannot tell whether a
  document was indexed or whether the store is stale.
