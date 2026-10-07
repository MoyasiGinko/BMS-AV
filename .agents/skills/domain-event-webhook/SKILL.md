---
name: domain-event-webhook
description: Publish a domain event through the transactional outbox and expose it as a webhook/automation trigger.
---
# Event + webhook recipe
1. Define the event in `apps/<name>/events.py`: `@dataclass(frozen=True) class InvoiceCreated(DomainEvent): invoice_id: int; ...`
   with `event_type = "invoice.created"`.
2. Publish inside the service transaction: `events.publish(InvoiceCreated(...))` (writes `OutboxEvent`, never sends directly).
3. Register in the event catalog `apps/core/event_catalog.py` with a payload serializer (this feeds webhook subscriptions, automation
   triggers, the API docs and the AI assistant's context).
4. Handlers (`@subscribe("invoice.created")`) must be idempotent: report summary updates, notifications, webhook fan-out, automation.
5. Webhook delivery: Celery task `deliver_webhook(delivery_id)`; HMAC-SHA256 signature of `timestamp.body`; exponential backoff; log in `WebhookDelivery`.
6. Tests: event written in same transaction (rolled back with it); dispatcher is idempotent on retry; webhook signature verifies; failing endpoint backs off and disables after N failures.
