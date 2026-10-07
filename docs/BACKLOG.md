# BACKLOG (agent: work top to bottom; tick `[x]` when done and `make verify` is green; `[!]` = blocked, see BLOCKERS.md)
Format: `ID title: Done when ...`

## P0 Foundations
- [x] P0-01 Scaffold project (Python 3.14, Django 6.1, `uv lock` committed, settings use MAILERS/CSP/Redis cache per docs/STACK.md; run `pip check` and fix any compatibility issue per STACK.md policy): config/ (settings base/dev/test/prod/prod_check, urls, api_urls, asgi/wsgi, celery), apps/ package, templates/static dirs, manage.py. Done when `make verify` passes on the empty project.
- [ ] P0-02 core base: TenantModel, TenantManager, tenant context var, TenantMiddleware (subdomain + membership fallback), money utils, base exceptions, NumberSequence. Done when architecture tests pass with sample model.
- [ ] P0-03 accounts: custom User (email), allauth config, login/logout/password reset/email verify screens, optional TOTP 2FA. Done when tests + UI smoke login pass.
- [ ] P0-04 tenancy: Organization, Membership, Role (+default roles), Invitation, Branch, Department, Warehouse, OrganizationSettings; org switcher; invite flow. Done when two orgs fully isolated in tests.
- [ ] P0-05 RLS: enable_rls helper + migration for all tenant tables + request/task context setter + test with raw SQL. Done when RLS test proves cross-org reads return nothing.
- [ ] P0-06 AuditLog + OutboxEvent + events.publish/subscribe + dispatcher task + event catalog. Done when atomicity/idempotency tests pass.
- [ ] P0-07 Permission engine: permission codes registry, role->permission, `permission_required`, `feature_required`, object scope helpers, view mixins. Done when 3-layer tests pass for web.
- [ ] P0-08 Celery + Redis wiring: base tenant-aware task, queues, beat schedule skeleton, `/healthz` `/readyz`. Done when a tenant task test passes.
- [ ] P0-09 UI foundation: tokens.css, Tailwind 4 build via django-tailwind-cli, vendored JS via scripts/vendor_frontend.sh, layouts (app shell, auth, public), full component library, `/_styleguide/` page, toasts, HTMX setup. Done when styleguide renders all components and UI smoke passes.
- [ ] P0-10 DRF foundation (apps/core/api): TenantScopedViewSet, permission classes, pagination, exception handler, idempotency, request-id, rate limiting, spectacular setup, JWT auth. Done when sample endpoint passes contract tests and schema validates.
- [ ] P0-11 Observability: structured JSON logging with request/org/user ids, Sentry hook (env-gated), security headers, `check --deploy` clean in prod_check settings.

## P1 SaaS shell
- [ ] P1-01 billing: Plan, Module, PlanModule, Subscription, ModuleRegistry (nav, permissions per module), UsageCounter, entitlement checks (web+API+tasks), seed plans (Starter/Growth/Business/Enterprise).
- [ ] P1-02 Signup + onboarding wizard: register -> create org -> choose plan/trial -> business profile (currency, tz, fiscal year) -> branch/warehouse -> invite team -> modules overview. Provisioning service creates defaults (roles, number sequences, plus a provisioning-hook registry that later modules plug into, e.g. accounting registers chart-of-accounts + mappings in P2-00) transactionally. Done when signup-to-working-workspace E2E passes.
- [ ] P1-03 Payment gateway adapter (+ fake gateway), subscription state machine, gateway webhook (inbound, idempotent), grace period -> read-only mode, plan change/upgrade UI, invoices for subscription.
- [ ] P1-04 Settings screens: organization, branches, warehouses, departments, users & roles (custom roles), numbering, tax codes, currencies, notification prefs.
- [ ] P1-05 API keys (scoped, hashed, last-used, rotation) + API key auth backend + usage metering + rate limits per plan; UI to manage.
- [ ] P1-06 Dashboard shell with widget registry (module/permission aware) and empty-state onboarding checklist.
- [ ] P1-07 Back-office (internal staff) app: tenant lookup, impersonation with audit + banner, subscription overrides, job/webhook inspection.

## P2 Small-shop MVP: Catalog, Inventory, Customers, Sales, POS
- [ ] P2-00 accounting core minimal: Account, AccountMapping, JournalEntry/Line, post_entry/reverse_entry, FiscalPeriod, chart-of-accounts templates seeded at provisioning, invariants tests.
- [ ] P2-01 catalog: categories, units, tax codes, products (+variants, barcode, images), price lists; screens + API + CSV import/export.
- [ ] P2-02 inventory ledger: StockMovement, StockLevel, costing strategy (weighted avg), reservations, services issue/receive/transfer/adjust/count; screens + API; reconciliation job + test.
- [ ] P2-03 customers: customer CRUD, addresses/contacts, balance ledger, statements, credit limit checks; screens + API.
- [ ] P2-04 sales documents: quote -> order -> invoice -> credit note, document numbering, discounts, taxes, confirm service with stock effect (posts through the accounting core from P2-00).
- [ ] P2-05 payments: customer payments, allocations to invoices, partial/over payments, refunds; balance + journal effects.
- [ ] P2-06 POS: registers, shifts (open/close with cash count and variance), fast checkout screen (barcode, quick keys, hold/resume, split tenders, discounts, returns), receipt (print CSS + PDF), POS checkout service reusing sales confirm. Done when POS checkout UI smoke passes and stock/ledger/balance update atomically.
- [ ] P2-07 Dashboard widgets v1: sales today, top products, low stock, receivables, recent activity. Reconciliation tests vs ledgers.
- [ ] P2-08 Reports v1: sales by product/customer/branch/day, stock valuation, stock movement, customer statement; export CSV/XLSX/PDF in background.
- [ ] P2-09 Import/Export framework (ImportJob/ExportJob, validate-preview-commit) + products/customers import.
- [ ] P2-10 Public API v1 for P2 modules (catalog, inventory, customers, sales, pos) fully documented in OpenAPI with idempotency on sales/payments.
- [ ] P2-11 seed_demo for "small shop" org + E2E: sell via POS and invoice, stock and balances correct.
- [ ] P2-R Phase review: `/verify` + `/review-module` for each module.

## P3 Growth bundle: Purchasing + full Accounting
- [ ] P3-01 purchasing: suppliers, PO (approval optional), goods receipt (stock in at cost), supplier bill, supplier payments, purchase returns; journal + balance effects; screens + API.
- [ ] P3-02 accounting full: manual journals, chart of accounts UI, bank accounts, reconciliation basics, expenses (+categories, receipts), multi-currency with exchange rates, period closing, tax summary.
- [ ] P3-03 financial reports: trial balance, P&L, balance sheet, cash flow, general ledger, aged receivables/payables, tax summary; reconcile tests; export.
- [ ] P3-04 Dashboard widgets v2: payables, expense trend, cash position, profit trend, branch performance.
- [ ] P3-05 Webhooks v1: endpoints UI, subscriptions, signed deliveries, retries, delivery log, redelivery; event catalog complete for P1-P3.
- [ ] P3-06 Recurring invoices + payment reminders (beat tasks) + email/notification framework (SMTP adapter + fake).
- [ ] P3-07 seed_demo for "growing company" + invariants suite complete (AR/AP/inventory subledgers vs control accounts).
- [ ] P3-R Phase review.

## P4 People: CRM + HR + Payroll
- [ ] P4-01 CRM: leads, opportunities, pipelines/stages (kanban with HTMX), interactions, tasks, tags, lead->customer conversion, customer 360 view, inactive-customer segments.
- [ ] P4-02 HR core: employees (encrypted sensitive fields), positions, departments link, documents, status lifecycle; self-service profile.
- [ ] P4-03 Attendance + leave: shifts, check-in/out (web + API), leave types/balances/requests/approvals, calendar.
- [ ] P4-04 Payroll: salary structures/components, payroll run (draft -> review -> approve -> pay), payslips PDF, accounting posting (expense + liabilities + payable), expense linkage.
- [ ] P4-05 HR/Payroll reports + dashboard widgets (headcount, attendance, payroll cost, employee performance basics).
- [ ] P4-06 seed_demo for people modules; permissions tests (HR data visible only to HR/owner).
- [ ] P4-R Phase review.

## P5 ERP maturity
- [ ] P5-01 Multi-branch: branch-scoped permissions, consolidated vs per-branch reports, inter-branch transfers.
- [ ] P5-02 Advanced inventory: batches/expiry, serials, FIFO costing strategy, reorder suggestions, stock count workflow.
- [ ] P5-03 Approvals engine: configurable approval rules (PO over X, expense over Y, payroll, discounts) with inbox UI.
- [ ] P5-04 Reporting engine: saved reports/filters, schedules (email), summary tables (DailySalesSummary etc.), report builder for basic custom reports.
- [ ] P5-05 Connector framework: registry, IntegrationConnection (encrypted), ExternalReference, sync log; connectors generic_rest, csv_import, fake_payments, fake_sms, smtp_email, zapier_compat.
- [ ] P5-06 OAuth2 provider (PKCE + client credentials) with consent screen, app registry UI, scopes; inbound webhook endpoints framework.
- [ ] P5-07 Full-tenant export/import (data portability) + retention settings + GDPR-style deletion/export workflows.
- [ ] P5-08 Notifications center (in-app + email), user notification preferences.
- [ ] P5-R Phase review.

## P6 Operating system layer
- [ ] P6-01 Automation engine: rules (trigger/conditions/actions), templates (low stock reorder draft PO, overdue reminders, win-back), run history, plan limits, UI builder.
- [ ] P6-02 AI assistant: provider abstraction (fake default + real adapters via env), tool registry over selectors/services (sales summary, low stock, inactive customers, profit change explanation, draft PO), permission-aware execution, draft/confirm action flow, chat UI (HTMX), AiAuditLog, usage limits, evaluation test set with the fake provider.
- [ ] P6-03 "What needs attention today" intelligence panel on the dashboard (rule-based insights first; AI summary optional).
- [ ] P6-04 Analytics: cohort/retention for customers, product ABC analysis, margin analysis, forecasting basic (moving average) for reorder.
- [ ] P6-05 Mobile-friendly PWA shell for POS and approvals (manifest, service worker for static assets, responsive polish).
- [ ] P6-R Phase review.

## P7 Hardening & delivery
- [ ] P7-01 Performance pass: indexes review, query-count tests, caching of dashboard widgets, bulk operations.
- [ ] P7-02 Security pass: tenant isolation suite complete, rate limits, `pip-audit`, `check --deploy` clean, secrets handling, CSP.
- [ ] P7-03 Production packaging: Dockerfile, docker-compose.prod.yml (web, worker, beat, db, redis, caddy/nginx), env docs, backup/restore scripts.
- [ ] P7-04 Documentation: README, per-module READMEs, user help pages in-app, API guide with examples (curl + Python), integration guide (webhooks/API keys/OAuth).
- [ ] P7-05 E2E business story test (see `.agent/workflows/final-audit.md`) + full UI walkthrough polish pass against the design system.
- [ ] P7-06 `/final-audit` and `docs/EVALUATION.md`.
