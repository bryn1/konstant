---
name: ui-quality
description: The quality floor for any user interface - every state (loading, empty, error, partial, success), keyboard and screen-reader basics, contrast, narrow-width layout, honest copy, restraint. Load when building or reviewing a page, component or form.
---
# UI quality floor

Applies to internal tools as much as to public pages. None of it is announced as a feature; all of
it is checked.

## Every view has all its states

- **Loading**: visible within a moment; no layout jump when data arrives.
- **Empty**: says what would appear here and invites the next action ("No invoices yet - create
  one").
- **Error**: says what happened and how to fix it, in the user's words; keeps the user's input.
- **Partial**: some data failed; show what loaded and mark what did not.
- **Success**: confirms the result where the user is looking.
If the page needs data it does not have, show that honestly; never fake content or ship placeholder
text.

## Accessibility basics

- Semantic elements (button, link, heading levels, lists, tables for tabular data); a label for
  every control; alt text that carries meaning (empty for decoration).
- Everything reachable and operable by keyboard in a sensible order, with a visible focus ring;
  Escape closes what it opened; no keyboard trap.
- Text contrast at least 4.5:1 (3:1 for large text and UI boundaries); information never carried by
  colour alone.
- Respect reduced-motion preferences; motion only where it explains something.
- Status changes announced (an aria-live region for async results and errors).

## Layout

Works at 375 px wide with no horizontal scroll; touch targets at least 44 px; long words, long
names and non-ASCII text do not break the layout; no content hidden behind fixed headers.

## Copy is design material

Active voice; name actions by what the user controls ("Save changes", not "Submit"); consistent
terms for the same thing across pages; numbers with units; dates in the user's format.

## Restraint

Typography and spacing carry the hierarchy; spend boldness in one place; remove one decoration
before calling it done. Avoid the generic templated look: the design should be recognisably about
this product. Reuse the project's tokens and components instead of inventing a second set.

## Check before done

A browser pass over each state (skill `exploratory-qa`), keyboard-only through the main flow, a
375 px screenshot, and the console clean.
