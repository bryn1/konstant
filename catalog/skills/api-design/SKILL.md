---
name: api-design
description: Design and change HTTP APIs contract-first - read the existing surface, request/response models before handlers, one route and error convention, pagination, idempotent retries, user-vs-system errors, structured logging, timeouts on every external call. Load when adding or changing endpoints or service error handling.
---
# API design: contract first, one convention, safe to retry

## Read the existing surface first

List the routers, the schema naming style, the error idiom and the auth dependency already in use.
New endpoints join an existing router and copy its conventions; a second convention for any of
these is a design change, not an implementation detail.

## Contract before handler

- Request and response models first: they are the spec. An explicit response model per endpoint;
  never return raw ORM objects or ad-hoc dicts (fields leak, the contract drifts). Separate input
  and output models (server-set ids and timestamps do not belong in input).
- Validate at the boundary (types, ranges, lengths, enums for closed sets); past it, data is trusted.
- Timestamps are UTC, timezone-aware, ISO-8601 in JSON.

## Routes and methods

Plural resource nouns, nesting at most two levels; verbs only for genuine actions, as a POST
sub-resource (`POST /orders/{id}/cancel`). GET never mutates; PUT replaces and is idempotent; PATCH
updates partially; a repeated DELETE answers 404 or 204, never 500.

## One error shape for the whole API

Use the project's shape; if none exists, register one, e.g.
`{"error": {"code": "validation_error", "message": "...", "details": []}}`. Status discipline: 400/422
invalid input · 401 unauthenticated · 403 forbidden · 404 absent (also for "exists but not yours") ·
409 conflict or duplicate · 500 is a bug, with a generic message and the details in the log only.
Never a 200 with an error body; never internals (paths, SQL, stack traces) in a response.

## Lists and retries

- Any list that can grow is paginated from day one (`limit` with a server maximum, plus offset or
  cursor) and returns `{"items": [...], "total": n}`; filters and sort fields are allow-listed.
- POST-that-creates is guarded by a unique constraint on the natural key, the integrity error mapped
  to 409 (or to the existing resource for ensure-exists semantics). Never check-then-insert: that
  is a race. Multi-step mutations run in one transaction.

## Errors and observability

- Classify every failure: **user error** (4xx, actionable message, logged at info or warning) or
  **system error** (500/503, generic message, logged at error with full context). Never blur them.
- No bare or silent excepts; catch only what you can recover from, convert or annotate and
  re-raise with the cause chained. One place maps domain errors to responses.
- Required configuration is validated at startup: a service that starts has valid config.
- Structured, one-line log events with ids and context; never secrets, personal data or whole
  request bodies.
- **Every external call has a timeout** and a stated behaviour when the dependency is down (usually
  503). Retry only idempotent operations, bounded (two or three, with backoff).
- A health endpoint for liveness, a readiness variant that checks the database.

## Done means

The failing HTTP test was written first and now passes against a running server; error cases
(422, 404, 409) are asserted with their bodies; no new swallowed exception; every new external call
has a timeout; one test exercises a dependency failure.
