---
name: exposure-gate
description: Extra steps for work that reaches people outside the project - money, public endpoints, outbound messages, collected personal data, publishing under someone's name - file it before building, owner approval before any payment path, no unproven claims, run it like a service. Load before building or changing anything a stranger could reach.
---
# Exposure gate: crossing from "our machines" to "other people"

You are in this class if the thing can: take money · message or serve people other than the owner ·
expose a public endpoint, bot or channel · collect sign-ups, emails or personal data · publish under
the owner's or a company's name. Building it is usually fine; building it unannounced is the harm.

## 1. File it before you build it

A board job at design time, not at completion, stating what it does, who can reach it and what it
asks of them. The owner must be able to learn about anything aimed at other people from the board,
never by someone finding it on disk later. A design without a section for the outward-facing part
has not designed that part.

## 2. Money is a hard gate

Never write a payment path, a price, a paid tier, a donation flow or any message asking a person
for money without the owner's approval recorded on the job first. **A placeholder is not safe**:
"contact X to subscribe" in live code is one edit from taking real money with no receipt, refund
or verification path. If the mechanism must be scaffolded, leave it unreachable and unreferenced,
and say so on the job. Money carries legal and tax duties (consumer protection, regulated advice)
that land on the owner; surface them, never assess them yourself.

## 3. No claim you have not proven

Any accuracy, return, speed or "X % better" figure shown to outsiders traces to a measurement you
can point at, from code without known bugs. Saying nothing is always safe; an unbacked number is
not.

## 4. Outward-facing means it runs like a service

A process in your session is not deployment: it dies with the session and does not return after a
reboot. Use a supervised service that restarts on boot, and state on the job how it is monitored
and how the owner stops it.

## 5. Do not build on known debt

If open jobs describe credential or hygiene problems in the code you are extending, close them
first instead of working around them.

## The test

If a stranger used this tomorrow, would the owner already know it exists, and would they have agreed
to what it asks of that stranger? If either answer is no, stop and file the job first.
