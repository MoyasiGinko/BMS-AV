---
trigger: model_decision
description: Use when creating or changing models, querysets, middleware, auth, permissions, tasks, uploads, or anything touching tenant data or security.
---
# Tenancy & Security Rules

- Shared database, shared schema, `organization` FK on every tenant row. `TenantModel` + `TenantManager` (auto-scoped via a context
  variable set by middleware). The unscoped manager is named `all_tenants` and only used in system code with a comment saying why.
- Resolve tenant by subdomain, falling back to the user's active `Membership`. No tenant => 404/redirect to org picker, never a global query.
- PostgreSQL Row-Level Security as defense in depth: policies on tenant tables using `current_setting('app.current_org')`, set per
  request/transaction/task. A migration helper (`apps.core.rls.enable_rls(model)`) must be called for every tenant model; a test asserts it.
- Celery tasks take `organization_id` and activate the tenant context via a base task class. No ambient tenant in tasks.
- Three permission layers on EVERY entry point (web, API, task, AI tool): `feature_required('module.feature')` (plan) ->
  `permission_required('app.action')` (role, per-org customisable) -> object scope (branch/warehouse via scoped querysets).
- Auth: custom `User` (email login) from the first migration; session+CSRF for web; JWT for first-party clients; hashed, scoped API keys
  and OAuth2 for external clients. API keys: show once, store hash, record last-used.
- Encrypt integration credentials and sensitive HR fields at field level (`EncryptedTextField` using `FIELD_ENCRYPTION_KEY`).
- Uploads: validate type/size, random storage names, tenant prefix, signed URLs for download.
- `AuditLog` (append-only) for sensitive changes: who, what, when, object, before/after.
- Never use raw SQL without parameters. Never `mark_safe` user input. Never disable CSRF except on signature-verified inbound webhooks.
- Required tests for each tenant feature: org A user cannot list/read/update/delete org B objects through UI, API, export and task.
