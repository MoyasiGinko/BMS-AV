# Design System: "Calm Ledger"

**Direction**: a trustworthy, dense-but-calm business tool. Clean surfaces, strong typographic hierarchy, restrained color, numbers treated as first-class
(tabular figures, right-aligned). Feels like a modern finance product (Stripe/Linear/Xero lineage), not a legacy ERP and not a marketing site.
Anti-patterns: gradients as decoration, rainbow dashboards, giant rounded cards everywhere, emoji icons, center-aligned tables, low-contrast gray-on-gray.

## Tokens (see `static/css/tokens.css`, the single source of truth)
- **Brand**: ink-teal `--brand-600 #0F766E` (actions), `--brand-700` hover, `--brand-50` tints. **Neutrals**: slate scale on warm-cool balance (`--n-0 #fff` ... `--n-900 #0f172a`).
- **Semantic**: success `#15803d`, warning `#b45309`, danger `#b91c1c`, info `#1d4ed8`, each with `-bg` and `-border` tints. Status never relies on color alone (icon + label).
- **Type**: Inter (UI) with system fallback; `font-variant-numeric: tabular-nums` on all numeric cells. Scale 12/13/14(base)/16/20/24/30. Weights 400/500/600. Mono: JetBrains Mono for codes/SKUs.
- **Space**: 4-pt grid (4, 8, 12, 16, 24, 32, 48). **Radius**: 6 (inputs/buttons), 10 (cards/modals). **Shadow**: `--shadow-sm` for cards, `--shadow-lg` for modals/popovers only.
- **Motion**: 120-180 ms ease-out; respect `prefers-reduced-motion`.
- **Dark mode**: all tokens have dark counterparts under `[data-theme="dark"]` and `prefers-color-scheme`.

## App shell
Left sidebar (240px, collapsible to 64px icons; groups = modules from registry; active state = brand tint + left bar), top bar (org + branch switcher, global search `Cmd/Ctrl+K`, quick-create "+", notifications, user menu),
content fluid full-width (`--content-max: 100%`) with 16-32px responsive gutters, sticky page header (title, breadcrumb, primary action right-aligned). Mobile: sidebar becomes a drawer; POS/approvals optimized at 360px; wide/ultrawide displays seamlessly utilize full viewport without artificial capping.

## Components (live in `templates/components/`, demonstrated in Theme Manager at `/settings/theme/?tab=styleguide`)
button (primary/secondary/ghost/danger, sizes, loading), input/select/textarea/checkbox/radio/switch/date/money input (currency prefix, tabular), form_field (label, hint, error, required),
badge/status_pill (draft, posted, paid, overdue, void...), card, kpi (value, delta with arrow + sign, sparkline slot), data_table (sticky header, sortable, row selection, bulk bar, density toggle, numeric right-aligned, row actions menu, empty state),
pagination, filter_bar (search + chips + saved filters), tabs, modal & drawer, dropdown/menu, toast, alert/banner, empty_state (icon, headline, one-line help, primary CTA), skeleton, breadcrumb, stepper (onboarding), timeline (audit/activity), avatar,
page_header, confirm dialog (typed confirmation for destructive), kanban column/card (CRM), chart wrapper (Chart.js with token colors), document header/lines editor (invoice/PO line items with inline add/remove and live totals).

## Key screen patterns
- **List**: page header -> filter bar -> data_table -> pagination; bulk actions appear in a sticky bar; export menu; saved views.
- **Document (invoice/PO/bill)**: left = header fields + line editor; right (sticky) = totals, status, actions; below = payments/stock/journal/activity tabs showing linked records ("follow the money").
- **Detail (customer/product/employee)**: summary header with KPIs, tabs (Overview, Transactions, Documents, Activity).
- **Dashboard**: 4 KPI cards on top (Sales today, Receivables, Payables, Low stock), then a "Needs attention" list, trend charts (sales 30d, expenses), top products/customers, branch comparison (if multi-branch). Widgets respect module + permission.
- **POS**: full-height two-pane: left product grid/search + categories + barcode input always focused; right cart with line qty steppers, discounts, customer picker, totals, big "Charge" button; tender modal with quick cash amounts and split payment; offline-tolerant UI states; large touch targets (>=44px).
- **Onboarding**: stepper wizard with progress and skippable steps; empty dashboard shows checklist ("Add products", "Invite team", "Make first sale").
- **Reports**: parameter bar (period, branch, compare), result table + chart, export, schedule.
- **Forms**: single column, grouped sections, inline validation on blur, errors summarized at top for long forms, primary action bottom-right (sticky on long forms), `Esc` closes modals.

## Content & formatting
Sentence case. Buttons are verbs ("Create invoice"). Dates `12 Mar 2026` (org format configurable); money with org currency symbol, 2 dp (4 dp in cost fields), negative in parentheses on financial reports; empty values show an em dash.

## Accessibility
WCAG AA contrast, visible focus ring (`--focus-ring`), full keyboard operation (tables, menus, modals trap focus), ARIA labels on icon buttons, `aria-live` toasts, form errors linked with `aria-describedby`, no information by color alone, reduced-motion support.

## Icons
Lucide icon set via inline SVG sprite (`static/icons/sprite.svg`), 16/20px, stroke 1.75, `currentColor`.

## Definition of "design done"
Uses only tokens + components; passes keyboard walkthrough; has empty/loading/error states; looks right at 360, 768, 1280, 1920px; light and dark; styleguide updated if a component was added.

## Reference images
Put inspiration/target screenshots in `docs/design/reference/` (png/jpg/webp). When present, they outrank generic taste: match their density, hierarchy and feel while still using the tokens and components. `reference-screens.html` is the baseline target.
