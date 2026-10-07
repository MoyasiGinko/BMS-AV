---
description: Screenshot and critique every screen touched by a task at mobile, tablet and desktop widths, in light and dark, against the design reference; fix defects.
---
# /visual-qa <screens or module>
Run after every task that changes templates/CSS, and for every module at its phase review.

1. Start the dev server (`make run`) with seeded demo data (`make seed`), logged in as the role that uses the screen.
2. With the browser tool, open each touched screen and capture screenshots at 360, 768, 1280 and 1920 px wide, in light and dark theme,
   plus its empty, loading, error and validation-failure states. Save to `docs/design/qa/<task-id>/` (keep only the latest set).
3. View `docs/design/reference/reference-screens.html` (and any images in `docs/design/reference/`) and compare against the screenshots on:
   hierarchy and spacing on the 4-pt grid, token-only colors, numeric columns right-aligned with tabular figures, component reuse
   (no ad-hoc markup), status pills with icon+label, sticky headers/actions, focus rings, no horizontal page scroll, touch targets >= 44px on POS.
4. Check functional UI facts in the page: no console errors, no failed network requests, HTMX swaps keep scroll/focus, modals trap focus,
   keyboard-only walkthrough reaches every control.
5. Write each defect as a one-line list in your scratch notes, fix all of them, re-capture, repeat until clean (max 3 rounds; then log in `docs/BLOCKERS.md`).
6. Accessibility spot-check: contrast of text/badges against tokens, labels on every input, `aria-label` on icon buttons.
7. Commit `ui(<task-id>): visual QA fixes`. Do not ask the user to look at anything.
