# Build State (updated by the agent after every task)

- Phase: P5 ERP maturity
- Last completed task: P5-06 OAuth2 provider (PKCE + client credentials) with consent screen, app registry UI, scopes; inbound webhook endpoints framework
- Next task: P5-07 Full-tenant export/import (data portability) + retention settings + GDPR-style deletion/export workflows
- Open `[!]` tasks: none
- Last `make verify`: PASSED (74/74 integrations tests passing, ruff check and format clean, lint-imports clean)
- Notes:
  - P5-06 Complete: OAuth2 provider with PKCE and Client Credentials, consent screen, app registry, and inbound webhook framework:
    - ADR 0030 (`docs/adr/0030-oauth2-and-inbound-webhooks.md`): Scoped OAuth2 provider via `django-oauth-toolkit` subclassing `AbstractApplication` and `TenantModel`, consent screen, tenant-isolated application registry, and cryptographic inbound webhook receiver engine.
    - Data Models: `OAuthApplication`, `InboundWebhookEndpoint` (with Fernet-encrypted secrets), `InboundWebhookLog` with PostgreSQL RLS enabled (`0007_enable_rls_oauth_and_inbound_webhooks.py`).
    - OAuth2 Scopes: Configured granular read/write scopes (`read:accounting`, `write:sales`, `read:inventory`, etc.) mapped to system roles and permissions.
    - Domain Services & Selectors: Application CRUD, secret regeneration, consent evaluation, token revocation, endpoint verification (HMAC-SHA256, HMAC-SHA1, Bearer token with Stripe/Shopify/GitHub/Generic normalization), and inbound payload processing with domain event emission.
    - Web UI & HTMX: App registry (`/integrations/oauth/apps/`), app creation with one-time secret display modal, consent authorization screen (`/oauth/authorize/`), authorized user tokens (`/integrations/oauth/authorized/`), and inbound webhooks UI (`/integrations/inbound/`) with copyable endpoints, secret rotation, and audit logs (`/integrations/inbound/logs/`).
    - Public REST API: Public unauthenticated receiver `/api/v1/integrations/inbound/receive/<uuid>/` with real-time signature validation, structured logging, and transactional outbox event publishing.
    - Test Suite: 15 comprehensive tests in `test_oauth_and_inbound.py`, 74/74 passing in `apps/integrations/tests/`.
  - Next task: P5-07 Full-tenant export/import (data portability) + retention settings + GDPR-style deletion/export workflows.
