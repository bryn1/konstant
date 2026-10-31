---
name: brainstorm
description: Turn a raw idea into a written design - one clarifying question at a time, diverge wide from several deliberately different angles, condense hard with an accounted-for kill list, propose 2-3 approaches with trade-offs, write it down, self-review. Load when an idea is still fuzzy, before planning or building.
---
# Brainstorm: diverge wide, condense hard, write it down

## 1. Understand the idea

Read what exists for the project first. Ask clarifying questions **one at a time** (purpose,
constraints, success criteria), multiple-choice when it fits. If the idea is really several
independent projects, say so and split before spending questions on details.

## 2. Frame it once

One paragraph: the idea, the audience, the constraints, what "good" would look like. Every angle
below gets this same frame.

## 3. Diverge (independent angles)

Explore from deliberately different perspectives, in parallel when you can spawn helpers (each gets
the frame and one perspective; none sees the others), otherwise one after another in fresh passes:

- **Minimalist**: the cheapest, simplest version that still delivers the core value.
- **Maximalist**: the most capable version if constraints were loose.
- **User advocate**: what the person using it actually needs, and what would annoy them.
- **Skeptic / inverter**: how this fails, and what the opposite approach would look like.

Each angle writes its ideas to its own file (paths, not pasted content, travel between rounds).
Optional further rounds: cross-pollinate (each angle reads the others' files and builds on the best
ideas), then invert and salvage (take rejected ideas and ask what would make them work). Stop by
corpus size, not by round count: when the material is more than can be condensed well, condense.

## 4. Condense (a reviewer, the only judgement step)

Every idea is either kept (with the reason) or killed (with the reason), grouped per angle and
round with counts; the header states `ideas_in_corpus` and `ideas_accounted_for`, and if they
differ the condense failed and is redone. Then a salvage pass over the kills: review the reviewer;
anything wrongly killed comes back with the reason.

## 5. Propose and write

Two or three approaches, each with its trade-offs; lead with the recommendation and why; cut what
does not earn its complexity. Present the design section by section, scaled to how non-obvious each
part is: what it is, how the pieces relate, what could go wrong, how anyone would know it works.
Save it as a dated design file in the project (`docs/` or the run's OUT); a new version supersedes,
never overwrites.

## 6. Self-review

Fresh eyes on the written document: no TBDs, no requirement loose enough to mean two things, no
contradiction between sections, every assumption stated. Then it can go to planning (design type).
