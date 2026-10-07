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
- Dark mode via tokens (`prefers-color-scheme` + `data-theme`). No hard-coded colors outside tokens.
- UI smoke tests (Playwright, marked `ui`) for: signup, login, create product, POS checkout, create invoice, view dashboard.
