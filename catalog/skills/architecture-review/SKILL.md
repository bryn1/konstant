---
name: architecture-review
description: Judge an approach before it is built - does it already exist, does it solve the reported problem, invariant vs convention, honest trade-offs with a baseline, blast radius and reversibility, gated sequencing - and end with SHIP, FIX or RECONSIDER. Load when designing, reviewing a design, or choosing between approaches.
---
# Architecture review

The output is a judgement with reasons. The most valuable outcome is often "this should not be
built", then "this already exists", and only then "build it this way".

## 0. Does it already exist?

Before judging a proposal on its merits, look for the mechanism it duplicates, searching by concern.
A request for "a new alert channel" is often answered by a health checker that already runs with an
escalation path; the right change is a few entries, not a new checker. A second mechanism beside a
first splits attention and the unwatched one rots: a proposal for a new mechanism says what happens
to the old one (retired, superseded, kept and why).

## 1. Reported problem vs solved problem

Write both sentences side by side: what the person reported, and what the change actually does. A
change that works perfectly and solves a different problem must not be reported as the fix; it may
even make the real problem worse.

## 2. Invariant or convention?

An **invariant** must hold or the system is wrong; you can name concretely what breaks. A
**convention** is currently true for consistency. Defending a convention as an invariant causes
paralysis; treating an invariant as a convention causes breakage. Say which is which; an invariant
nobody wrote down is itself a finding.

## 3. Trade-offs, honestly

- Every proposal has a cost; a review that lists none is incomplete.
- Quantify, and check it is the right number: freed capacity is not throughput. Say which axis a
  benefit lands on and against which baseline, measured how.
- Quality attributes as scenarios with numbers ("95 % of requests under 200 ms"), never adjectives.
- Every abstraction, wrapper and layer names its caller and why the caller cannot hold the logic.
  Prefer the design that adds the least cognitive load while meeting the requirement.
- Name what you could not verify (UNVERIFIED) and the instrument that would settle it.

## 4. Blast radius and reversibility

What breaks if this is wrong (degrade or outage)? How do we roll back (a long answer means a wrong
design)? Does it fail open or closed, and is that right for this concern? How would anyone notice
it stopped working? Is a half-applied change safe to re-run? One host or many (first one, verify,
then the rest)?

## 5. Sequence with gates

Order steps by dependency; each has an observable gate ("p95 under 200 ms on the target hardware",
not "acceptable performance"). Put the cheapest falsifier first. Mark owner-only steps
(irreversible, destructive, external) and stop there.

## 6. Verdict

**SHIP** (what you checked, including what you tried to break and could not) · **FIX** (the minimum
change set that flips you to SHIP, concrete enough to act on) · **RECONSIDER** (what you would do
instead and what evidence would change your mind). Always include what you tried to refute and
could not.
