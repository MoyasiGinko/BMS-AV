# API & Integration Specification

- Base `/api/v1/`; schema `/api/schema/`, docs `/api/docs/`. Auth: session (web), `Authorization: Bearer <jwt>`, `X-API-Key: <key>`, OAuth2 bearer.
- Resource groups: `auth`, `organization`, `catalog`, `inventory`, `purchasing`, `sales`, `pos`, `customers`, `crm`, `accounting`, `hr`, `payroll`, `reports`, `automation`, `integrations`, `ai`.
- Conventions: plural nouns, UUID ids (`public_id`), cursor pagination (`?cursor=&page_size=`), `?search=&ordering=&updated_after=&expand=&fields=`, `Idempotency-Key` on money/stock POSTs, `ETag/If-Match`,
  `429 Retry-After`, error body `{code, message, details, request_id}`, `X-Request-ID`.
- Scopes: `<module>:read|write` + `admin`. API keys carry scopes + optional IP allow-list.
- Webhook events (minimum catalog): `invoice.created|posted|paid`, `payment.received`, `sale.confirmed`, `purchase.received`, `stock.low`, `stock.adjusted`, `customer.created|updated`, `product.created|updated`,
  `payroll.approved`, `expense.created`, `employee.created`, `subscription.changed`. Signature: `X-Signature: sha256=hex(hmac(secret, timestamp + "." + body))`, `X-Timestamp`, replay window 5 min.
- Connectors shipped: `generic_rest` (configurable pull/push with field mapping), `csv_import`, `fake_payments` (sandbox gateway), `fake_sms`, `smtp_email`, `zapier_compat` (REST hooks subscribe/unsubscribe endpoints).
- Import/export: CSV/XLSX with validate -> preview -> commit, row error report, background job; per-module export + full tenant export (zip of JSON/CSV).
- Public (unauthenticated) endpoints are limited to: signup, login/token, health, invitation accept, inbound webhooks (signature-verified).
