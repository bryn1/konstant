---
name: exploratory-qa
description: Click through a running web app in a real browser the way a user would - load, read the DOM, interact, read the state back, screenshot at desktop and 375 px - and report issues with evidence. Load for UI verification, frontend test phases, or a QA pass over a running app.
---
# Exploratory QA in a browser

Use whatever browser automation the harness offers (a browser tool, Playwright, a headless
browser script). If none is available, every interaction claim is UNVERIFIED, never PASS, and the
report says why.

## Hard rules (they make it evidence)

1. **A tool error is a FAIL of that step**: "element not found", a timeout, a stale reference. Record
   it; never retry another target and report success.
2. **References go stale**: after any navigation, page-changing click or submit, take a fresh
   snapshot before the next element-based action.
3. **Read the state back**: after an action, prove its effect from a new snapshot or a DOM query and
   quote the exact text. "I clicked it" is not evidence.
4. **Look, then judge**: describe what is literally painted in a screenshot, then compare with what
   was expected. Exact colours, sizes and counts come from DOM queries, not from your eyes.
5. **Evidence under `OUT/.tmp/browser/`** with absolute filenames (create the directory first);
   cite the paths in DONE.md.

## The pass

1. **Plan**: the routes, the navigation, the key flows (sign-up, search, create, checkout), forms,
   error and empty pages.
2. **Per page**: load it; read console warnings and errors and failed network requests (any 404
   asset or uncaught exception is a finding); snapshot the accessible tree; screenshot.
3. **Exercise**: click, type, submit, select, keyboard-only (Tab, Enter, Escape), back navigation;
   invalid input, empty submission, very long text, non-ASCII characters, double clicks.
4. **Responsive**: resize to 375 x 812, screenshot again; horizontal scroll (`scrollWidth >
   innerWidth`) is a finding.
5. **Report**: per issue a screenshot, URL, steps to reproduce, expected vs actual, console lines,
   severity (critical, high, medium, low) and category (functional, visual, accessibility, console,
   UX, content); de-duplicate; counts by severity; what was tested, what was NOT, and every step
   that errored.
