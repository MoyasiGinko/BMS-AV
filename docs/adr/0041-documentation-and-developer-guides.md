# ADR 0041: System Documentation, In-App Help Center, REST API Guide, and Developer Integration Manual

## Context
A mission-critical multi-tenant SaaS ERP requires comprehensive, discoverable, and accurate documentation across all user and developer touchpoints. This includes a master repository README for developers and evaluators, per-module documentation for modular maintainability, in-app interactive help pages for business operators, an end-to-end REST API guide with curl and Python code samples, and an integration guide detailing webhooks, cryptographic HMAC verification, API key governance, and OAuth 2.0 PKCE.

## Decision
1. **Master System README (`README.md`)**:
   - Authored an exhaustive front-door manual detailing the platform's mission, technology stack (Python 3.14, Django 6.1, PostgreSQL 18, Redis 8, HTMX 2, Alpine.js 3, Tailwind 4, Celery 5.6, uv), 19 functional module matrix, local/production quickstart guides, developer commands (`make verify`, `make setup`), and architectural invariants.

2. **Per-Module Documentation Matrix (`apps/<app>/README.md`)**:
   - Ensured 100% documentation coverage across all 20 apps in `apps/`.
   - Added missing module documentation for `apps/accounts/README.md`, `apps/billing/README.md`, and `apps/tenancy/README.md`, standardizing on domain models, service layers, selectors, event publishing, and interface contracts.

3. **In-App User Help Center (`/help/`)**:
   - Implemented `apps.core.help_views` and `apps.core.help_urls` providing:
     - Main Help Center overview (`/help/`) with live search over 12 operational domains (Onboarding, Sales & Invoicing, Purchasing & Bills, Inventory, POS, General Ledger, CRM, HR & Payroll, Approvals, Integrations, Reports, AI Copilot) and interactive FAQ accordion.
     - Live search HTMX partial (`help/partials/_topic_cards.html`) with instant debounced filtering.
     - Comprehensive article view (`/help/<slug>/`) with sticky table-of-contents, anchor jumping, and related guides.
     - Helpfulness feedback action (`/help/<slug>/feedback/`) submitting HTMX ratings.
     - Linked directly into the primary application navigation layout (`templates/layouts/app.html`).

4. **REST API Developer Guide (`docs/API_GUIDE.md`)**:
   - Documented authentication schemes (API keys, OAuth2 bearer, session tokens), standard request headers, dynamic plan-tier rate limiting, cursor pagination, and standard error formats.
   - Provided complete, runnable `curl` and `Python` examples for Authentication, Catalog, Customers, Sales Invoices (with `Idempotency-Key`), Payments, Inventory Adjustments, Webhook Registration, and an end-to-end Python SDK client class.

5. **Integration & Webhooks Guide (`docs/INTEGRATION_GUIDE.md`)**:
   - Detailed integration channels: API keys, OAuth 2.0 PKCE / Client Credentials, Inbound Webhooks, and Outbound Webhooks via transactional outbox.
   - Provided cryptographic HMAC SHA-256 signature verification algorithms with complete code implementations in Python (Flask) and Node.js (Express), including 5-minute replay attack defense.
   - Documented retry backoff schedules, Dead-Letter Queue (DLQ) mechanics, and Dynamic Client Registration (RFC 7591).

## Consequences
- End-users and operators have immediate, contextual guidance without leaving the application.
- Integrators and third-party developers have copy-pasteable, verified curl and Python code snippets for all major business workflows.
- Modular monolith maintainability is strengthened by explicit architectural boundaries recorded in each module's README.
