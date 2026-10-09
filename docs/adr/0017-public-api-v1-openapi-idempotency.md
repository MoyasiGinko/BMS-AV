# 17. Public API v1 OpenAPI Specification and Mutating Idempotency

Date: 2026-10-10

## Context
Phase 2 introduced multiple business modules: Product Catalog, Inventory, Customers, Sales, and Point of Sale (POS).
As specified in `docs/03-api-and-integrations.md` and Task P2-10, external clients and frontends require a fully documented
public REST API under `/api/v1/` with guaranteed exactly-once processing (idempotency) on critical financial and stock mutations
(sales order creation/confirmation, invoice issuance/posting/voiding, credit notes, payments reception/allocations/refunds,
and POS checkout/shift operations).

## Decision
1. **OpenAPI Documentation**: Every ViewSet across the 5 modules (`apps/catalog`, `apps/inventory`, `apps/customers`,
   `apps/sales`, `apps/pos`) is decorated with `@extend_schema_view` and custom `@extend_schema` tags (`Catalog`, `Inventory`,
   `Customers`, `Sales`, `POS`), summaries, request schemas, and typed responses. Strict validation via `python manage.py spectacular --validate --fail-on-warn`
   must succeed with zero warnings.
2. **Idempotency Engine**: Used `apps.core.api.idempotency.idempotent` with `IDEMPOTENCY_KEY_PARAMETER` on all mutating operations.
   Cache keys incorporate tenant and user isolation (`idempotency:{org_id}:{user_id}:{key}`).
   - Matches replay with identical payload: returns cached response payload and HTTP status with `Idempotent-Replayed: true` header.
   - Replay with mismatching payload raises `409 Conflict` (`idempotency_key_mismatch`).
   - In-flight requests lock with temporary "processing" flag to guard concurrent races.
3. **Automated Quality Testing**: Added end-to-end integration test suites covering order creation, order confirmation,
   invoice posting, payment recording, POS checkout, and cross-tenant key isolation.

## Consequences
- Guaranteed safe retries for clients and webhook/connector consumers encountering network drops.
- Zero duplicate ledger postings or double inventory deductions on retried transactions.
- Clean OpenAPI 3.0 specification generated dynamically and validated against `drf-spectacular`.
