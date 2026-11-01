# AGENTS.md: rules for AI agents working on BMS-AV

This is the single source of truth for how to work in this repo. If another rule file disagrees with this one, this one wins. Do not create new rule, plan, or notes files.

## 1. What we are building

A multi-tenant business management platform (POS, sales, inventory, purchasing, accounting, CRM, HR, reports) on Django. Requirements that shape every decision:

- **Any country, any business type.** Nothing about a country, currency, tax, language, payment method, or business type may be hardcoded. Bangladesh is the first market (BDT, Bangla, VAT, bKash/Nagad) and is delivered as configuration, not as special cases in code.
- **Everything is a module or feature that can be switched on or off per client.** Clients are delivered with a profile (modules, features, payment methods, roles, branding, language).
- **A full POS** that keeps working offline, with returns, exchanges, refunds, dues (baki), loyalty and promotions.
- **Money and stock are always correct.** Accounting integrity beats speed and beats convenience.

Roadmap and the current phase live in `docs/ROADMAP.md`. Do not start an item from a later phase unless told to.

## 2. Non-negotiable rules

1. **Money is `Decimal`, never `float`.** Every amount has a currency. Use the existing money helpers. Decimal places and rounding come from the currency and organization settings, not from literals like `2`.
2. **Tenant isolation.** Every tenant table inherits `TenantModel`. Use the default manager. `all_tenants` is allowed only inside services and management commands, and the line must carry a comment saying why. Never write a query that can cross organizations. Keep row-level security and its tests passing.
3. **Posted documents are immutable.** Never edit or delete a posted invoice, payment, credit note, journal entry, or stock movement. Correct them by reversal or by a new linked document.
4. **All ledger and stock effects go through services.** Post journals with `accounting_services.post_entry`, move stock with the inventory services. Views, templates, serializers, and tasks never write to the ledger or stock tables directly.
5. **Every posting runs in a transaction, locks what it changes (`select_for_update`), checks the fiscal period is open, and is idempotent.** Retrying the same request must not double-post.
6. **No hardcoded business values.** Never hardcode `USD`, a tax percentage, a country, a payment-method list, a chart-of-accounts code, a language, or a document prefix. Read them from organization settings, `TaxCode`, payment-method records, the number-sequence service, and the active locale.
7. **No dummy or filler content.** No lorem ipsum, no "Acme", "John Doe", or "example@", no fake data in templates, fixtures, docs, or tests meant for production paths. See section 9 for demo data.
8. **Do not invent compliance rules.** For VAT, Mushak forms, EFD/SDC, VDS, and any statutory format, implement only what is written in `docs/compliance/`. If the rule is missing or unclear, stop and ask. Mark compliance output as "pending review by a VAT professional" in the task summary.
9. **Secrets.** No secrets, tokens, or real credentials in code, docs, seeds, or logs. Use environment variables and `.env.example`.

## 3. How to work on a task

1. **Read before writing.** Find the existing code that does something similar and extend it. Search the repo first.
2. **State a short plan** (what files you will touch and why) before large changes. Keep each change small and reviewable: one concern per commit.
3. **Edit existing files before creating new ones.** Create a new file only when the structure requires it. Never create a file "for notes", "for the plan", "for the summary", or a one-off script.
4. **Do not add documentation per task.** Docs are updated only when behavior or setup changes. Record an architecture decision (ADR) only for a real, lasting architectural choice, and keep it to one page.
5. **No leftovers.** No commented-out code, no debug prints, no unused imports, functions, templates, or CSS, no `TODO` without an issue ID (`TODO(BMS-123)`), no generated files committed (OpenAPI schemas, compiled CSS, resolved-version lists are built by CI).
6. **No new dependencies, apps, top-level directories, or public API changes without asking.**
7. **Finish with the checks in section 12 and a short report** (section 13).

## 4. Naming conventions

Follow PEP 8 and enforce with `ruff` (including the `N` naming rules).

| Thing | Convention | Example |
|---|---|---|
| Python files | `snake_case`, named for the use case, not the layer alone | `invoicing.py`, `returns.py` |
| Models | Singular PascalCase noun. No vague names (`Data`, `Info`, `Item`, `Helper`, `Manager`) | `SalesInvoice`, `SalesReturn` |
| Status enums | `<Model>Status` using `TextChoices` | `CreditNoteStatus` |
| Fields | `snake_case`. Booleans `is_`/`has_`/`can_`. Dates `*_date`. Timestamps `*_at`. Money `*_amount` next to a `currency`. Rates `*_rate`. Counts `*_count` | `posted_at`, `refund_amount` |
| Foreign keys | Named after the target, without `_id` | `customer`, `warehouse` |
| Services | `verb_noun`, keyword-only arguments, domain exceptions, one public function per use case | `post_credit_note`, `void_payment` |
| Selectors (read-only) | `get_`, `list_`, `count_`, `exists_` | `list_overdue_invoices` |
| URL names | `<entity>_<action>`, namespaced per app | `sales_invoice_detail`, `sales_invoice_post` |
| Templates | `<app>/<entity>_<action>.html`; partials in `<app>/partials/_<name>.html` | `sales/invoice_detail.html` |
| Permissions | `<module>.<action>` (existing format) | `pos.refund` |
| Feature keys | `<module>.<feature>`, lowercase | `pos.loyalty`, `payments.bkash` |
| Events and webhooks | `<module>.<entity>.<past_tense>` | `sales.invoice.posted` |
| Settings and env vars | `UPPER_SNAKE_CASE`, documented in `.env.example` | |
| Migrations | Descriptive, one concern, reversible. Never `auto_*` | `0042_add_payment_method_process_mode` |
| Tests | `test_<behavior>_<condition>`, mirror the module path | `test_refund_blocked_when_period_closed` |
| Commits and branches | Conventional Commits (`feat(pos): ...`), branch `feat/pos-returns` | |
| Static assets | `kebab-case` | `pos-terminal.js` |

Pick the product name once (see `docs/ROADMAP.md`) and use it everywhere: titles, emails, settings, seed data.

## 5. Structure and size

- Each app keeps the layers: `models`, `services`, `selectors`, `views`, `urls`, `permissions`, `tests`. Respect the import-linter contracts. Do not reach across layers.
- **Files stay under 600 lines.** When a file grows past that, turn it into a package split by use case (for example `sales/services/invoicing.py`, `payments.py`, `returns.py`).
- `apps/core` is for genuinely shared infrastructure only. Do not add new feature logic to it. Do not put tax logic in `tenancy`. Move such code when you touch it, and mention it in the report.
- Views are thin: parse input, call a service or selector, render. Business rules never live in views, templates, or serializers.

## 6. Modules and feature toggles

- Every user-visible capability (screen, API endpoint, menu item, report, dashboard widget, background task, webhook) belongs to exactly one **module** or **feature** key.
- Modules declare `depends_on`. Enabling a module requires its dependencies. Do not allow a configuration that breaks one.
- **Engine vs. screens.** Ledger posting, stock movement, and number sequences are engines and always run. Turning off a module hides its screens and blocks its API. It never deletes data and never stops engines that other modules rely on.
- Resolution order: core, then plan, then per-organization override (explicit on or off), then dependency validation.
- Enforce in all of: navigation, URL/view, API permission, background tasks, dashboard widgets, reports, event delivery.
- **Keep the coverage test passing:** every URL pattern maps to a module or feature. A new route without a key fails CI.
- Client choices are tenant settings, never `if client == ...` code. Defaults for the first client are in its profile; everything else remains switchable.

## 7. Localization and Bangladesh readiness

- Every user-visible string uses `gettext`. No hardcoded English in templates, services, errors, or emails.
- Use `babel` or Django localization for numbers, dates, and currency. Support lakh/crore grouping, the ৳ symbol, per-currency decimals (0, 2, 3), optional Bangla digits, and `dd/mm/yyyy`.
- Bangla must render correctly everywhere, including receipts and PDFs. For thermal printers, render Bangla receipts as raster images.
- **CSS uses logical properties only** (`margin-inline-start`, `padding-inline-end`, `text-align: start`). No `left`/`right` for layout. This keeps RTL possible.
- Country behavior (chart of accounts template, tax codes, invoice formats, e-invoicing) comes from country packs as data, not from `if country == "BD"`.

## 8. POS, offline, and returns

**POS and offline**
- Offline sales use client-generated UUIDs and an idempotent server checkout endpoint. A retried sync must never double-post.
- Receipt and invoice numbers for offline registers come from pre-allocated blocks per register. Gaps are recorded as void, never silently skipped (statutory serials may need to be unbroken).
- Pricing, promotion, loyalty, and tax calculation are deterministic and data-driven, so the client and the server compute the same result. The server re-verifies on sync.
- Offline conflicts (for example overselling the last unit) are accepted and flagged for review, never lost.
- Payment methods are tenant records with a `process_mode` (`manual_verify`, `gateway`, `record_only`), a settlement account, an optional fee, and rules for Tx ID or proof. Pending manual verification holds the stock reservation until confirmed or rejected.

**Returns and exchanges**
- A return traces to the original sale line and keeps the original price, discount share, tax rate, and unit cost. Track `quantity_returned` per line and reject returning more than was sold.
- Separate the physical return (`SalesReturn`: reason code, condition, disposition) from the financial credit note and the money refund.
- Dispositions: sellable, open-box, quarantine, write-off, back to supplier. Accounting follows the disposition.
- One settlement step nets returned value against new items and fees, then settles by cash, original method, store credit, or reduction of the customer's due.
- Void, return, and exchange are different actions with different permissions. Return policy (window, receipt required, approval threshold, restocking fee, refund methods, non-returnable categories) is configuration.

## 9. Demo and seed data

- Production code and templates contain no sample data.
- Demo data lives in a single `--demo` management command, is never run in production, and models a small realistic Bangladesh shop (BDT, VAT as configured, local product names).
- Demo credentials are never written in docs or committed files.

## 10. UI, design, and accessibility (definition of done for every screen)

- Use design tokens and the shared components. No hardcoded hex colors, spacing, or font sizes in templates. New patterns go into the component library, not into one page.
- Every screen works in all four themes. The neumorphic theme stays opt-in and its text and control contrast must meet WCAG AA.
- Accessibility: semantic HTML, labels on every control, keyboard operable, visible focus, modals trap and return focus, tables have proper `scope`/captions, HTMX swaps announce changes with `aria-live`. `axe` checks pass in CI.
- POS screens: touch targets at least 44px, usable one-handed on a tablet, keyboard shortcuts, an on-screen numeric keypad, and optional sound or haptic feedback on scan.
- Lists use the shared data-table component (sticky header, column chooser, saved views, bulk actions, export).
- Every screen has real empty, loading, error, and success states. Destructive actions confirm and are undoable where possible.
- All on-screen text follows the rules in "Text, titles, and labels" below.

### Text, titles, and labels

The words on screen must be minimal, relevant to the task, and understandable by a shop owner, cashier, or accountant. They must not read like marketing copy or like developer notes. Every new or changed string follows these rules.

**Principles**
- Write for the person using that screen. Cashier screens use plain words (sale, receipt, due, refund). Owner screens use business words (profit, stock). Only accountant screens use accounting words (journal, ledger).
- Use short, literal sentences with no idioms, jokes, or wordplay. Every string will be translated into Bangla, so long or clever text is costly and gets translated badly.
- **Delete test:** if removing a sentence loses no information the user needs to act, delete it.
- The UI does not explain how the system works internally and does not sell the product. Put one-time explanations in the help pages.

**Where text goes**
- **Page title:** a noun that names the page, 1 to 4 words ("Invoices", "Stock transfers"). No taglines.
- **Page description:** omit it unless it adds something the title does not say. Never restate the title ("Manage and issue customer invoices" under "Invoices" is removed). One sentence, at most 12 words.
- **Buttons:** verb plus noun, 1 to 3 words ("Create invoice", "Refund", "Save"). Never "OK", "Yes", "Submit", or "Click here".
- **Table headers and field labels:** 1 to 3 words, nouns.
- **Help text:** only when the label alone is ambiguous, at most 12 words. Prefer a better label.
- **Empty state:** one short line and one action, at most 8 words plus a button ("No invoices yet." with [Create invoice]). Never just "No X found" with no next step.
- **Errors:** say what happened and what to do, at most 20 words, with no blame and no codes ("You can't refund more than was paid. Enter 500 or less.").
- **Confirmations:** name the object and the consequence, at most 25 words. The confirm button repeats the action ("Delete connection"). Say it cannot be undone only when that is true.
- **Success messages:** past tense, 1 to 4 words ("Invoice saved"). No exclamation marks.
- Use sentence case. No ALL CAPS, no emoji, and no exclamation marks.

**Forbidden**
- Marketing and filler words: seamless, effortless, powerful, robust, comprehensive, unlock, empower, streamline, leverage, supercharge, intuitive, insights, "at a glance", "in one place", "enterprise-grade", "all-in-one", "AI-powered" (except on the AI assistant itself).
- Chatty phrases: "Oops!", "Great news!", "Welcome back!", "Let's get started", "Please note that", "In order to".
- Internal or technical terms in user-facing text: Celery, worker, domain event, payload, sync run, entitlement, tenant, slug, GL, "lookback window", "data subject". Use the user's word ("plan" not "entitlement", "customer" not "data subject").
- Describing implementation ("A periodic worker dispatches schedules at midnight"). Say what the user gets ("Runs every night").
- Text that appears only for SaaS plans or subscriptions when the deployment mode is dedicated.

**Consistency**
- One word per action across the whole product. Use this glossary and extend it only by editing this file: *Create* (not Add or New), *Delete* (permanent) vs *Cancel* (stop before it happens) vs *Void* (reverse a sale or entry), *Save*, *Edit*, *Refund*, *Return*, *Receipt*, *Due* (money owed), *Stock*, *Supplier*, *Customer*, *Branch*, *Warehouse*.
- The same concept keeps the same name in menus, titles, buttons, reports, and receipts.

**Examples of the target style**

| Instead of | Write |
|---|---|
| Secure enterprise management platform | (remove, or "Sign in to your account" on the login page) |
| Manage and issue customer invoices. (under "Invoices") | (remove) |
| No invoices generated yet | No invoices yet. [Create invoice] |
| Upon opening your shift, you will enter the full-screen cash register interface with instant barcode scanning, discount rules, split payments, and thermal slip printing. | Open a shift to start selling. |
| Your subscription is unpaid or the past-due grace period has elapsed. Creating or modifying records is temporarily restricted. Please select an active plan or settle outstanding invoices below to restore editing privileges. | Your subscription has expired. You can view data but not edit it. Pay the invoice or choose a plan to continue. |
| Are you sure you want to delete connection "X"? All sync logs, external reference mappings, and encrypted credentials will be permanently erased. | Delete "X"? Its sync history and saved credentials will be removed. This can't be undone. |
| Total debits strictly equal total credits. Once posted, financial journal entries cannot be edited or deleted; corrections are handled exclusively via reversal entries. | Posted entries can't be edited. To fix one, reverse it. |
| Calculates daily sales velocity (run rate) over lookback windows. Projects days of inventory remaining, stockout risk dates, and recommended purchase order quantities. | Days of stock left for each product and how much to reorder. |
| Segments products into Class A (crucial 80% revenue drivers), Class B (moderate 15%), and Class C (low 5% or stagnant)... | Products grouped by sales: A sells the most, C the least. |
| No widgets are currently visible for your user role and plan entitlements. | Nothing to show here. |

**Enforcement**
- A CI check scans translatable strings (`makemessages` output). It fails on forbidden words and on strings over the length limits above. Legal or privacy text can be allowlisted with a reason.
- In every task report, list the new or changed UI strings so a human can review the wording.
- Do not add placeholder text while building a screen. Write the real, short text or leave the element out.

## 11. Security and audit

- Check permissions at the service boundary, not only in views. Sensitive actions (refund, price override, void, stock adjustment, write-off) need their own permission and write an audit log entry with who, what, when, and old and new values.
- Validate all input. Never trust client-calculated amounts for posting.
- Rate-limit and idempotency-key every endpoint that moves money or stock.
- Never log full payment identifiers, tokens, or personal data.

## 12. Definition of done (run before reporting)

1. `ruff` (lint and naming), `vulture`, `djlint`, import-linter, and the file-length check pass.
2. Tests exist for the behavior you changed, including failure cases, and the full suite passes. Accounting changes must keep the AR, AP, and inventory reconciliation invariant tests green.
3. For accounting, stock, or tax changes: a test proves the journal balances and stock matches the ledger.
4. Money-path code has tests for rounding, multi-currency, and zero-decimal currencies.
5. Migrations are reversible, have descriptive names, and are safe on a large table.
6. The module/feature coverage test and the tenant-isolation tests pass.
7. No new warnings, no unused code, no stray files (`git status` is clean apart from intended changes).
8. Strings are translatable, CSS uses logical properties, and the accessibility checks pass.
9. All new or changed UI text follows "Text, titles, and labels" and the copy check passes.
10. Scenario IDs from `docs/scenarios/` that the change covers are referenced in the test names or docstrings.

## 13. Reporting back

End each task with a short report:

- **Changed:** files and behavior, in a few lines.
- **UI text:** the new or changed on-screen strings, listed for review.
- **Decisions and assumptions:** anything you chose where the request was silent.
- **Not verified:** what you could not test or confirm. Do not claim something works if you did not run it.
- **Needs a human:** compliance rules, accounting treatment, data migrations, or anything on the stop-and-ask list.

## 14. Stop and ask before

- Changing how money, tax, or inventory is calculated or posted
- Anything involving statutory compliance (VAT, Mushak, EFD/SDC, e-invoicing)
- Migrating, deleting, or rewriting existing production data
- Adding a dependency, an app, a top-level directory, or changing a public API
- Handling payment gateway credentials or webhooks
- Anything the roadmap places in a later phase
- A request that conflicts with a rule in this file

## 15. First tasks (repo hygiene, before new features)

1. Add `.gitattributes` with `export-ignore` for AI and dev-only folders, so a clean client build comes from `git archive`.
2. Merge the other rule files (`GEMINI.md`, `GSD-STYLE.md`, `PROJECT_RULES.md`, `START-HERE.md`, and the `.agent`, `.agents`, `.gsd`, `.gemini` content) into this file, then remove the duplicates.
3. Move ADRs about demo seeding and one-off decisions to `docs/archive/`. Stop committing generated schema and resolved-version files.
4. Keep one deploy configuration, remove the duplicate, and keep only the script variant the team uses.
5. Remove demo credentials from the README. Unify the product name.
6. Set up `ruff` naming rules, `vulture`, `djlint`, the file-length check, and `axe` in CI.
7. Run a copy audit: export all translatable strings to one list, and rewrite every string that breaks "Text, titles, and labels" (long explanations, developer terms, buzzwords, titles that repeat themselves, empty states with no action). Fix the "order order" style typos found along the way.
8. Then begin Phase 0 from `docs/ROADMAP.md`: module/feature registry with overrides and dependencies, dynamic payment methods, tax code linkage, number sequences with void tracking, currency and rounding, localization plumbing.
