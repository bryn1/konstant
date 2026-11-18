---
name: external-exposure-gate
description: How to build anything that reaches people outside your team - money, public bots/channels, signups, emails, or a service strangers can reach. Gate money on explicit owner approval, and run it as a real service. Use BEFORE writing the first line of such a feature.
---

# Crossing from "our machines" to "other people"

Almost all development work stays internal. A small class of work **reaches real people outside
it** — that class needs three extra steps. This skill is how to do that work well, not a ban on
doing it.

**You are in this class if the thing you are building can:**
take money · message or serve people who are not the owner · expose a public endpoint, bot, or
channel · collect signups, emails, or personal data · publish under the owner's name or a company name.

## 1. Document it before you build it

Owner-facing work needs a written record **at design time, not at completion**. The record states
what it does, who can reach it, and what it asks of them. The owner must be able to find out about
a feature aimed at other people from the project record, never by someone inspecting the filesystem
later.

If a design doc has no section for the outward-facing part, that part is not designed. Write it
before coding it. Pricing improvised straight into code is the specific failure this rule exists for.

## 2. Money is a hard gate — owner approval, recorded, first

**Never write a payment path, a price, or any message asking a person for money without explicit
owner approval recorded first.** That includes:
- payment instructions of any kind ("pay via X", a wallet address, a bank/payment-app handle)
- a paid tier, subscription, or price string — even a placeholder
- a checkout, invoice, or donation flow

**A placeholder is not safe.** `contact [REDACTED] to subscribe` shipped in live code is one edit
away from taking real money from real strangers, with no receipt, refund, or verification path.
Ship no version of it. If you need the mechanism scaffolded, leave it **unreachable and
unreferenced**, and say so in the project record.

Money also carries legal weight that lands on the owner personally: charging for financial signals
or advice is regulated in many jurisdictions, personal payment apps have tax consequences, and
taking payment creates consumer-protection duties. Surface them and let the owner decide.

## 3. Never claim performance you have not proven

Any accuracy, win-rate, return, or "X% better" figure shown to an outside person must trace to a
measurement you can point at. If the code that produces the number has known bugs, the number is
not evidence. Saying nothing is always safe; an unbacked number is not.

## 4. Outward-facing means it runs like a service

If people depend on it, a background shell job under your own agent process is not deployment — it
dies with your session and does not come back after a reboot. Use a systemd unit with
restart-on-boot, and document how it is monitored and how the owner stops it.

## 5. Fix the debt you are building on

If open tickets already describe hygiene or credential problems in the workspace you are extending
(secrets in `.env`, missing dependencies, stray files), close them rather than building on top and
working around them. Shipping a new outward-facing feature over known debt compounds it.

## The test

Before you write the feature, ask: **if a stranger used this tomorrow, would the owner already
know it existed, and would they have agreed to what it asks of them?** If either answer is no,
stop and document the design first.
