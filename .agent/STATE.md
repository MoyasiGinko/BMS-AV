# Build State (updated by the agent after every task)

- Phase: P3 Growth bundle: Purchasing + full Accounting
- Last completed task: P3-05
- Next task: P3-06
- Open `[!]` tasks: none
- Last `make verify`: PASSED (35/35 integrations tests pass including 16 webhooks tests, ruff clean, system check clean, openapi schema validated)
- Notes:
  - P3-05 Webhooks v1 completed:
    - Event catalog for P1-P3 domain events implemented in `apps/core/event_catalog.py` (40+ events across all modules).
    - `WebhookEndpoint` and `WebhookDelivery` tenant-scoped models with indices and migrations applied.
    - HMAC-SHA256 signature signing (`X-Signature: sha256=...`), timestamp replay window (5m), Celery async delivery, exponential backoff retries ([10, 60, 300, 1800, 3600]), auto-disable after 10 consecutive failures.
    - Outbox fanout listener hooked in `IntegrationsConfig.ready()`.
    - Server-rendered templates with HTMX partials: endpoint list, creation/editing form, detail screen with secret show/rotate, test ping trigger, delivery audit log, and modal inspection.
    - DRF REST API endpoints under `/api/v1/integrations/webhooks/` and `/deliveries/` with OpenAPI spec validation.
    - 16 new webhook tests covering signature, replay window, fanout, backoff, auto-disable, manual redelivery, permissions, tenant isolation, and REST API.
  - Next task: P3-06 Recurring invoices + payment reminders (beat tasks) + email/notification framework (SMTP adapter + fake).
