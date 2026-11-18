---
name: describe-image
description: Get a literal description of an image (screenshot, render, photo) from a vision model - what is actually painted on a page, not what the DOM says. Use when you need to know what is visible on screen - blank, garbled, overlapping, unreadable, wrong text - which curl and DOM checks cannot see.
---

# describe-image — ask a vision model what is on the screen

Use this skill when you need to verify **painted** claims — the things a DOM assertion cannot
prove:
- Is the page blank, garbled, or overlapping?
- Is the text readable, and what does it actually say (verbatim)?
- Did the layout collapse? Is an element covering another?

**Do NOT use it for deterministic claims.** Element exists, computed color equals a token, no
console error, no overflow — those belong to headless browser checks with explicit assertions,
which answer them exactly. A vision model cannot read an exact hex value or a pixel count, and
asking it to is how you get a confident wrong answer.

## The rule that matters: it REPORTS, you JUDGE

Ask the vision model to describe literally what is visible. That is deliberate. A vision model
asked *"does this look right?"* will tend to agree with whatever it is shown. So:
- Ask **"what text is in the banner?"**, not "is the banner correct?"
- Ask **"where is the button and what is its label?"**, not "is the button in the right place?"
- Then compare the description against what you expected, yourself

If the description does not mention something you expected to see, that is evidence the thing is
not painted — not proof, evidence. Look again with a targeted question.

## Getting the image

**Browser screenshot first.** If you have a browser tool available, use it to take a screenshot
directly. This is the preferred path for interactive pages.

**Headless screenshot as fallback.** If browser tools are not available, use a headless browser
to capture a screenshot:
```bash
# Pseudo-code — use whatever headless screenshot tool your project has
screenshot <url> --width 1280 --out /tmp/shot.png
```

Do not substitute a `curl` of the HTML for a screenshot when you need to verify rendered output.
HTML from curl does not tell you what the user actually sees.

## What it costs

A single screenshot call consumes one of the available inference slots for a few seconds. Do not
loop it over dozens of screenshots. Downscale to 1280 px on the long edge before sending.

## Failures are informative, not retryable

- Endpoint unreachable → vision is unavailable. Say so. Never guess what an image shows.
- Image missing or empty → say so. Do not substitute a DOM check for a rendered check.
- Model returned nothing useful → say the description could not be obtained. Raise `--max-tokens`
  if the response was truncated.
