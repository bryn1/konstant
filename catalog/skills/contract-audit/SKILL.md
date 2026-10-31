---
name: contract-audit
description: Find where docs, API definition, frontend calls, backend handlers, tests, configuration, deployment and runtime tell different stories about the same feature. Load when reviewing a change that crosses layers, when a feature works in one place and not another, or before calling docs current.
---
# Contract audit: do all the layers agree?

## Layers to compare

README and docs · API definition (routes, methods, payloads, status codes) · frontend calls ·
backend handlers · tests · configuration (env vars, config files, defaults) · deployment (compose,
units, proxy) · runtime behaviour.

## What to look for

- **Frontend/backend mismatch**: the client calls a shape the server does not serve (field names,
  casing, nesting, status codes).
- **Documented features that do not work**: the README promises, the runtime refuses.
- **Tests verifying a different contract**: asserting the current (possibly wrong) behaviour
  instead of the intended one.
- **Path and prefix drift**: trailing slashes, version prefixes, proxy rewrites that differ between
  development and deployment.
- **Obsolete configuration** (keys nothing reads) and **missing configuration** (code reading a key
  nothing sets, so a silent default decides).
- **Orphaned consumers**: a control or reader of a replaced component that now returns success and
  does nothing.
- **Stale docs**: removed flags, renamed endpoints, old examples.

## Method

1. Pick the feature or endpoint; read its documented claim.
2. Read the API definition and the handler, then the client call, then the test.
3. Check configuration and deployment for every key and path involved.
4. Exercise the runtime path (skill `verify`).
5. Record each layer's version of the contract; every disagreement is a CONTRADICTED finding naming
   both sides.

## Rules

A contradiction is a finding even when the system "works": silent drift compounds. The reference is
the intended contract (docs plus stated intent); the layer that disagrees is the defect, unless the
owner re-ratified the new behaviour, in which case the contract is updated and the decision
recorded.
