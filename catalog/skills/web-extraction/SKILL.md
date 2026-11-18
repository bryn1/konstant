---
name: web-extraction
description: Fetch order for web pages - browser tool first for JS-rendered content, then a scraping service, then plain curl. Use when deciding how to fetch a web page for content extraction.
---

# Web extraction — how to fetch a web page

Use this skill when you need to extract content from a web page and must choose the right tool
for the job.

## The fetch order

**1. Browser tool (primary, if available).** If you have a clickable browser tool (Playwright,
Puppeteer, or a browser MCP tool), use it first. It renders JavaScript, can handle authentication
flows, and returns the final DOM state the user would see. This is essential for:
- Single-page applications (React, Vue, Angular)
- Pages that require a login or cookie
- Content that loads after the initial HTML via JavaScript

**2. Scraping service (secondary).** If you have access to a web scraping or crawling service
that renders JavaScript, use it for pages where you do not need to interact but the page is
JS-heavy. This is faster than a full browser for read-only extraction.

**3. Plain curl / fetch (fallback).** For static pages or server-rendered content:
```bash
curl -s --max-time 30 -L -A "Mozilla/5.0 (compatible)" "<url>"
```
Use curl when:
- The page is static HTML or server-rendered
- You only need the raw HTML (not the rendered state)
- Speed matters more than completeness

## Choosing between approaches

| Need | Approach |
|------|----------|
| JS-rendered page | Browser tool |
| Login-gated content | Browser tool |
| Static page, fast | curl |
| Many pages, no JS | curl in a loop |
| Cookie wall | Browser tool (handle the cookie prompt) |
| Rate-limited target | Add delay between requests |

## Content extraction

After fetching:
- For structured data (prices, tables, metadata): parse the HTML with a proper parser, not regex
- For prose: extract the main content block; strip navigation, headers, footers
- For dynamic state (a count shown after login): use the browser tool and verify the DOM element

## Anti-patterns

- **Substituting a curl of the HTML for a rendered screenshot.** These answer different questions.
  curl shows the HTML; a screenshot shows what the user sees.
- **Assuming the first curl response is the final state.** Some pages redirect or update on
  subsequent loads.
- **Fetching a page without a timeout.** Always set a timeout; a hanging fetch blocks indefinitely.
