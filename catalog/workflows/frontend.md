---
description: Run a frontend task through placement plan, UI build, browser-based test, adversarial review and architecture check. Load when a task is [type:frontend] or the gate names workflow-frontend.
---
## Producer brief

- **Direction from something real**: the project's existing design system, tokens and components
  first; a new visual direction is a design decision written down before code (palette, type
  scale, spacing, one signature element), not improvised per component.
- **One component or view per step**, each with all its states (loading, empty, error, success)
  and its accessibility floor (skill `ui-quality`). Commit as you go.

## Verifying in a browser, never by curl

The tester drives the real page (skill `exploratory-qa`): load it with zero console errors and no
failed requests; check the claimed elements by accessible name; perform the claimed interaction and
read the resulting state back; screenshot at desktop width and at 375 px (no horizontal scroll);
keyboard-only pass on the main flow. Evidence lives under `OUT/.tmp/browser/` and is cited in
DONE.md. No browser available: every interaction claim is UNVERIFIED, never PASS.

The reviewer attacks clarity (can a first-time user finish the job of the page?), copy, states and
consistency with the rest of the product, not taste.

## Exit

As for code tasks: DONE.md rows per DoD line, `N1` and surface rows, CLEANUP line, the check exits
0, the job closes with the evidence.
