---
name: reuse-research-gate
description: Check prior art before building - search the existing codebase and knowledge store first, then do web research if the answer isn't found, then store the finding so the next builder skips the search. Use before starting any build to avoid rebuilding something that already exists.
---

# Reuse research gate — check before you build

Three mechanisms get rebuilt because the builder did not check whether they already existed.
This skill is the discipline that prevents that.

## STEP 0 — Check prior art (do this before writing a single line)

Search in this order:

1. **Your knowledge store.** Query your project's knowledge base or memory system for the
   topic. Use terms that name the concern, not the implementation ("session handling", not
   "SessionManager"). If your project has a knowledge store, this is the first call.

2. **The codebase.** Grep the repo for the concern. The existing thing is named differently —
   search by what it does, not what you would call it.

3. **Project docs.** Read `docs/ARCHITECTURE.md` if it exists. Read the README for referenced
   patterns.

If you find the thing: use it, extend it, or state why you cannot. Do not build a sibling.

## STEP 0.5 — Research gate (before building something genuinely novel)

If STEP 0 found nothing and you are about to build something using an unfamiliar library,
API, or approach:

1. **Search for prior usage.** Look for existing examples of this library or approach in the
   wild. Use web search if available.
2. **Read the actual docs.** Do not build from memory of the API. Fetch the documentation page.
3. **Check the installed version.** `pip show <package> | grep Version` or equivalent. API
   behavior varies between versions.

## STORE — write the finding back

After research, record the finding so the next builder skips the search:
- In your project's knowledge store (if one exists): store the key fact and the source
- In a comment in the code if the finding explains a non-obvious choice
- In `docs/` if the finding is architecture-level

A research result that lives only in your session is wasted: the next agent will repeat the
search.

## Anti-patterns

- **Building from memory of an API.** The version installed may differ from what you remember.
  Read the docs.
- **Searching by implementation name.** The existing thing is called something else. Search by
  what it does.
- **Storing in a local file and not committing it.** A finding that is not committed is not shared
  with the next builder.
- **Skipping STEP 0 because you're sure it doesn't exist.** Certainty without checking is the
  root cause of duplicate mechanisms.
