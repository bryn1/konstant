---
name: skill-authoring
description: Decide whether a new skill earns its place and write it in the catalog format - recurrence evidence, reuse check, an eval, a description that says when to load, an owning type - then wire it in catalog/types.yaml and run konstant agents sync. Load before adding, changing or retiring a skill.
---
# Skill authoring

A skill's description is listed in every session's context, forever. The question is never "could
this be a skill?" but "does it earn its place in the index?"

## The five criteria (all must pass)

1. **Recurrence**: name the occasions it was needed. One occurrence is a task, not a pattern.
2. **Reuse check**: search `catalog/skills/` and say why nothing covers it. If an existing skill is
   80 % right, improve it; two skills for one job make the model choose between duplicates.
3. **An eval ships with it**: the check that tells a future reader whether it still works and still
   helps (a worked example with the expected output, a scenario with a pass condition).
4. **A description that says when**, not just what: it is all the model sees when deciding to load
   it. Lead with the use case; say when not to load it if it shadows another skill.
5. **An owner**: which task types load it (`skills:` in `catalog/types.yaml`), or the orchestrator
   (`roles:`). If only one project needs it, it belongs in that project, not the catalog.

Not a skill: a one-off task, something agents already do well, a decision (write an ADR), or a
procedure for one project (its repository).

## Format

`catalog/skills/<name>/SKILL.md`, name lowercase-kebab and equal to the directory:

```
---
name: <name>
description: <what it does and when to load it, one paragraph, no angle brackets>
---
# <Title>
<the method: steps, rules, the check that proves it was followed>
```

Optional helper scripts go in `catalog/skills/<name>/scripts/` (standard library only, documented
in the SKILL.md). Keep it under 200 lines: distilled rules with a one-line why, no history, no
names of people, hosts or tickets.

## Wiring and checking

Add the name to the owning `skills:` list in `catalog/types.yaml`, then:

```
bin/konstant agents list          # the skill is listed and owned
bin/konstant agents sync          # renders .claude/skills/<name>/SKILL.md
bin/konstant agents sync --check  # exit 0: nothing drifted
```

The generated copy under `.claude/` is overwritten on every sync: always edit `catalog/`.

## Retiring

A library that only grows rots. A skill nobody loads is a retirement candidate: remove it from
`types.yaml` and `catalog/skills/` in one change (git history keeps it), and `agents sync` removes
the generated copy. A retired name is gone only when a search for it returns zero hits.
