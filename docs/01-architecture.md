# Architecture Specification

## Shape
Modular monolith. Django full-stack (templates + HTMX) is the primary UI. DRF REST API (`/api/v1/`) is an additive second interface over
the same service layer. Outbox-driven events power webhooks, automation, reporting summaries and the AI assistant.

```
Browser (templates+HTMX)        External apps / mobile / partners
        |                                   |
   Django views                      DRF /api/v1/
        \_______  services (business logic)  _______/
                    |         |          |
                 models    events     permissions
                    |         |
                PostgreSQL  Outbox -> Celery -> webhooks / automation / AI tools
```

## Repository layout
```
config/{settings/{base,dev,test,prod,prod_check}.py, urls.py, api_urls.py, asgi.py, wsgi.py, celery.py}
apps/{core,accounts,tenancy,billing,catalog,inventory,purchasing,sales,pos,customers,accounting,hr,payroll,
      reports,automation,integrations,ai_assistant}/
templates/{layouts,components,partials}/   static/{css,js}/   tests/{architecture,invariants,e2e,factories}/   docs/
```
`apps/core/` holds: `TenantModel/TenantManager`, tenant context + middleware, RLS helpers, `AuditLog`, `OutboxEvent` + `events.publish/subscribe`,
`NumberSequence`, `EncryptedTextField`, money utils, base services/exceptions, `core/api/` (DRF base classes), base Celery task, UI template tags.

Layer order (import contract): reports/ai/automation/integrations > pos/payroll > sales/purchasing/hr > accounting/inventory/customers >
catalog > billing/tenancy/accounts > core.

## Multi-tenancy
Shared DB + shared schema + `organization` FK. Tenant resolved by subdomain (fallback: active membership). Scoped default manager + RLS
(`app.current_org`). Org-leading unique constraints/indexes. Tasks carry `organization_id`. Isolation tests are mandatory (see tests/architecture).

## Auth & authorization
Custom email `User`; `Membership(user, organization, role, branches)`; roles = named permission-code bundles customizable per org.
Entitlement (plan/module/limit) -> role permission -> object scope, enforced identically in views, API, tasks, AI tools.
Web: session+CSRF (+optional TOTP 2FA). API: JWT (first-party), hashed scoped API keys, OAuth2 (PKCE, client credentials).

## Subscription & modules
`Plan(modules, limits, price)`, `Subscription(org, plan, status, trial_end, renews_at)`, `ModuleRegistry` maps app -> module key,
`UsageCounter` meters users/documents/API calls. Disabled module => hidden nav, 403 views/API, skipped automation. Payment gateway behind an
adapter (fake gateway included); webhooks idempotent; grace period then read-only mode.

## Events
`events.publish()` writes `OutboxEvent` in the caller's transaction; a Celery beat dispatcher (seconds) fans out to idempotent handlers
(summary tables, notifications, webhooks, automation, AI context). At-least-once delivery.

## Background jobs
Celery queues `critical, default, reports, bulk`. Beat: outbox dispatch, low-stock check, recurring invoices, subscription renewals,
payroll reminders, stock reconciliation, summary rebuilds, retention cleanup, webhook retries. Long work returns `202` + job resource.

## Reporting
Selectors first; pre-aggregated daily summary tables (sales by product/branch/customer/day, expense by category/day) updated by
event handlers + nightly rebuild; widgets registry for dashboards (module + permission aware); exports (PDF/XLSX/CSV) in background jobs;
all totals reconcile to ledgers (tested).

## Automation & AI
Automation: `AutomationRule(trigger event|schedule, conditions (declarative JSON), actions)`; run history; plan limits; templates (low-stock
reorder, overdue reminder, win-back, approval routing). AI assistant: tool registry wrapping selectors/services; runs as the user with the
same three permission layers; read-only first, write = draft/proposed action requiring user confirm in UI; full `AiAuditLog`; provider
abstraction with a deterministic fake provider for tests/offline (`AI_PROVIDER=fake|anthropic|openai|gemini`).

## Non-functional
i18n (gettext, org timezone/currency/format), accessibility (WCAG AA), structured JSON logs with request/org/user ids, Sentry hook, health
endpoints (`/healthz`, `/readyz`), security headers, `check --deploy` clean, rate limiting, backups documented, Dockerfile + compose for prod-like run.
