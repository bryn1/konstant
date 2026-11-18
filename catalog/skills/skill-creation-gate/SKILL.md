---
name: skill-creation-gate
description: Five criteria a new skill must pass before being added to the shared pool - recurrence, reuse, eval, owner ratification, and no duplication. Use before creating a new skill to decide whether it is worth adding.
---

# Skill creation gate — should this become a skill?

A skill in the shared pool costs maintenance. Every skill added is a skill that must be kept
current as the system evolves. Add skills that earn their keep; do not add skills for every
pattern you encounter.

## The five criteria

A new skill is worth adding when ALL of the following hold:

1. **Recurrence.** This pattern has occurred at least twice, in different contexts. A skill that
   encodes a one-off decision is a poor candidate. If it has only happened once, file a note
   and wait.

2. **Reuse.** The skill is general enough for agents other than the one that encountered the
   pattern. A skill that only applies to one specific project or configuration is not a pool
   candidate — keep it in that project's docs.

3. **Eval.** The skill ships with a way to check whether it still holds. This can be a worked
   example with a checkable outcome, a test that the instructions produce the right result, or
   a grep that would catch violations. A skill with no way to test it is a belief, not a
   verified procedure.

4. **Owner ratification.** The owner has seen the pattern and agreed that encoding it as a skill
   is the right level of investment. Do not add skills autonomously on the basis that "this
   seems like it would be useful".

5. **No duplication.** Check the existing pool before creating anything. Search by concern, not
   by name — the existing skill may be called something different. If a gap is real but small,
   the right change is an extension of an existing skill, not a sibling.

## When NOT to create a skill

- When the pattern has only appeared once
- When the pattern is project-specific or configuration-specific
- When the same content already exists in another skill under a different name
- When the right answer is simpler than a skill (a one-line rule in a profile, a checklist row in
  an existing skill, a comment in the relevant code)

## Format for a new skill

```
---
name: skill-name
description: One sentence - what triggers loading this skill (when to load) and what it covers.
---

# Skill title

[Body: the procedure, checklist, or doctrine. Keep it to one concern.]
```
