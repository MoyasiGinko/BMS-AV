---
trigger: model_decision
description: Use when creating or editing templates, CSS, HTMX interactions, forms, tables, dashboards, POS screen or any UI.
---
# Frontend & Design Rules

Follow `docs/design/design-system.md` exactly; tokens live in `static/css/tokens.css`; the living reference is `/_styleguide/`.

- Server-rendered Django templates; HTMX 2 for partials using **Django template partials** (`{% partialdef %}` in the same template file; views return `page.html#partial` when `request.htmx`);
  Alpine.js 3 for tiny local state. Tailwind 4 CSS-first (`static/css/input.css`, `@theme`), vendored JS in `static/vendor/` (no CDN). No SPA.
- Use only components from `templates/components/` (button, input, select, badge, card, data_table, modal, toast, empty_state, kpi,
  page_header, tabs, pagination). If a new component is needed, add it to the library AND the styleguide first.
- Every list screen: search, filters, sortable columns, pagination, bulk actions where relevant, export, empty state.
- Every form: inline validation errors, required markers, disabled-while-submitting, success toast, unsaved-changes guard on large forms.
- Every page: loading (skeleton/htmx-indicator), error, empty states; keyboard accessible; labels; contrast >= WCAG AA.
- Numbers right-aligned with tabular figures; money formatted by org currency; dates by org timezone/format.
- Responsive: usable at 360px (POS and approvals) up to 1920px; sidebar collapses; tables scroll horizontally inside their container.
- Dark mode via tokens (`prefers-color-scheme` + `data-theme`). No hard-coded colors outside tokens. Prevent dark mode CSS from corrupting or graying out light surfaces when viewing in light mode.
- Neumorphic & High-Contrast Design:
  * Zero borders on cards and containers.
  * Zero white drop shadows (no glowing white rings or blurry light halos).
  * High-contrast, tactile buttons: crisp white or dark bold text on solid vibrant backgrounds (e.g., solid blue, emerald, amber, rose). Never leave buttons washed out, murky, or grayed out.
  * Equal baseline layouts: grid items across pipeline columns must stretch to equal bottom baselines (`items-stretch` with `h-full`).
- Fast Visual Verification:
  * Always inspect the rendered UI (1-shot screenshot or browser preview) to visually verify design quality before completing a UI prompt.
  * Never run slow backend test suites (`pytest` with database creation) for pure styling or template adjustments.
  * Never enter retry loops on scratch screenshot scripts. Fail fast (<10s) and keep turnarounds under 30–45s.
- UI smoke tests (Playwright, marked `ui`) for: signup, login, create product, POS checkout, create invoice, view dashboard.
