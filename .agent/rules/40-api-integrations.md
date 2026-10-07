---
trigger: model_decision
description: Use when writing REST API endpoints, serializers, webhooks, API keys, OAuth, connectors, imports/exports or anything exposed to external systems.
---
# API & Integration Rules

- DRF under `/api/v1/`, router aggregated in `config/api_urls.py`. Shared base classes in `apps/core/api/`: `TenantScopedViewSet`,
  permission classes `HasModuleAccess`, `HasPermissionCode`, `HasBranchScope`, exception handler, pagination, idempotency, request-id.
- Serializers validate shape only. Writes call services. Domain exceptions -> one error body `{code, message, details, request_id}`.
- Actions as sub-resources (`POST /invoices/{id}/confirm/`). Cursor pagination for ledgers/lists that grow; page size capped.
- `Idempotency-Key` header supported on all money/stock-affecting POSTs (store key + request hash + response, 24h).
- `ETag`/`If-Match` (or `version` field) for editable documents. `?expand=`, `?fields=`, `?updated_after=`, filter allow-lists.
- Rate limits per API key/org tied to plan; `429` + `Retry-After`. Request IDs in logs and responses.
- OpenAPI via drf-spectacular must validate with `--fail-on-warn`; annotate with `@extend_schema` where needed.
- Webhooks out: endpoints + secrets + event subscriptions; outbox handler; HMAC-SHA256 (`X-Signature`, `X-Timestamp`); retries with
  exponential backoff; auto-disable after repeated failure; delivery log; manual redelivery.
- Webhooks in: `/api/v1/integrations/inbound/<provider>/`, signature-verified, raw payload stored in `InboundEvent` before processing,
  idempotent.
- Connector framework in `apps/integrations/`: `Connector` protocol (`connect, sync_inbound, handle_event, health_check`), registry,
  `IntegrationConnection` (encrypted credentials), `ExternalReference` for external ids, sync log. Provide at least a `generic_rest`
  connector, a `csv_import` connector and fake/sandbox payment + SMS connectors.
