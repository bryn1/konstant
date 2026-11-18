---
name: web-app-hosting
description: Make a web app hostable by construction - ship a valid hosting config at the repo root, bind the PORT env in the entrypoint, and run post-publish acceptance against the live URL before any published app counts as done. Use when building, scaffolding, extending, or publishing a web app.
---

# A web app is not done until it can be hosted

If a build's deliverable is a hostable web app, "it works on my machine" is not the finish line.
The finish line is: the repo carries a **valid hosting config at its root**, and its **entrypoint
binds the PORT environment variable**. Without these, a perfectly good app cannot be deployed by
an automated host.

## The two things you MUST ship

1. **A hosting config at the repo root.** This declares the app's name, type, and entry point
   to the hosting system. The exact format depends on your hosting platform, but the principle
   is universal: a machine-readable declaration at a predictable path.

2. **An entrypoint that binds the PORT environment variable.** For a service app, read the port
   from the environment:
   ```python
   # Python / uvicorn example
   port = int(os.environ.get("PORT", 8080))
   uvicorn.run(app, host="0.0.0.0", port=port)
   ```
   Do NOT hardcode a port. The host assigns the port dynamically.

## Hosting config schema (generic)

A minimal hosting config for a service app:

```json
{
  "name": "my-app",
  "type": "service",
  "exec": "server.py",
  "port": 8080
}
```

A minimal hosting config for a static app (files only, no server process):

```json
{
  "name": "my-site",
  "type": "static"
}
```

Required fields vary by platform. At minimum: `name`, `type`, and for a service: `exec` and
`port`.

## The common trap

The most common failure: the ASGI/WSGI `app` object lives in `src/app.py`, and there is no
servable entrypoint at the repo root. The hosting system quiet-skips the repo. Ship a root
entrypoint that imports and starts the app on `0.0.0.0:$PORT`.

## POST-PUBLISH ACCEPTANCE — a published app is not "published" until this passes

Owner ruling: *"once published I want to make sure the website is reachable when published and
that it renders correctly with vision and tools as well as testing every click, function and
page. This needs to be part of publish and project DoD."*

**Shipping the app is not publishing it. Publishing ends when the LIVE URL is proven to work.**

Before declaring a hosted web app done:

1. **Reachable**: the live URL returns a non-error response
2. **Renders**: take a screenshot and verify the page renders (not blank, not error)
3. **Functional**: exercise every click, page and core function through the live URL — not on
   localhost

A pre-push test suite proves the source works. The post-publish check proves the DEPLOYED SITE
works. Run both.

## Auth gate for private apps

**A private app that reaches public infrastructure must be auth-gated before deploy.** A running
service behind a missing authentication policy is a public URL — that is a FAIL, not a pass.

Before deploying a private or restricted app:
- Verify authentication is configured and tested
- From a machine that is not logged in, confirm that the app is NOT reachable without credentials
- Document the authentication mechanism in the hosting config or project README
