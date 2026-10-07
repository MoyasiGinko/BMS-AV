# ADR 0005: Payment Gateway Adapter, Subscription Lifecycle, and Webhook Idempotency
Status: accepted | Date: 2026-10-08
Context: Backlog item P1-03 requires integration with payment gateway operations (customers, subscriptions, charges), handling webhook lifecycles with strict idempotency, and enforcing read-only workspace access when payments are unpaid or grace periods expire.
Decision:
1. Created `PaymentGatewayAdapter` interface and a zero-dependency sandbox implementation `FakePaymentGateway` supporting HMAC-SHA256 signature verification, charge simulation, and synthetic webhook generation.
2. Created global model `billing.ProcessedWebhookEvent` to record processed webhook event IDs and ensure deduplication. Added to `GLOBAL_ALLOWLIST` in `tests/architecture/test_tenancy_audit.py`.
3. Created `SubscriptionReadOnlyMiddleware` that blocks mutating requests (POST/PUT/PATCH/DELETE) with HTTP 403 when a tenant subscription is unpaid or expired, while keeping `/billing/`, `/accounts/`, and health endpoints exempt so tenants can remediate billing issues.
Consequences: Development and CI test suites run hermetically without external network dependencies. Webhook handlers are strictly idempotent. Tenant workspaces enter read-only mode upon payment failure without losing data.
