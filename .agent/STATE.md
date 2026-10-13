# Build State (updated by the agent after every task)

- Phase: P5 ERP maturity
- Last completed task: P5-05 Connector framework: registry, IntegrationConnection (encrypted), ExternalReference, sync log; connectors generic_rest, csv_import, fake_payments, fake_sms, smtp_email, zapier_compat
- Next task: P5-06 OAuth2 provider (PKCE + client credentials) with consent screen, app registry UI, scopes; inbound webhook endpoints framework
- Open `[!]` tasks: none
- Last `make verify`: PASSED (59/59 integrations unit/isolation/API/views/connectors tests passing, ruff lint and format clean, lint-imports clean)
- Notes:
  - P5-05 Complete: Pluggable connector framework with encrypted connection storage, external reference mappings, and 6 built-in adapters:
    - ADR 0029 (`docs/adr/0029-connector-framework.md`): Pluggable adapter pattern via `BaseConnector` and `ConnectorRegistry`, symmetric Fernet encryption for connection credentials at rest, bidirectional external reference index, and immutable sync logs.
    - Data Models: `IntegrationConnection`, `ExternalReference`, and `IntegrationSyncLog` with RLS policies enabled (`0005_enable_rls_connector_framework.py`).
    - Connectors Package: `generic_rest`, `csv_import`, `fake_payments`, `fake_sms`, `smtp_email`, and `zapier_compat` auto-registered in singleton `connector_registry`.
    - Domain Services & Selectors: CRUD, connection testing, sync runs, discrete action execution, and Zapier REST hook subscriptions in `apps.integrations.services` and `selectors`.
    - Celery Background Tasks: `sync_integration_connection_task` and periodic `sync_due_integration_connections_task` in `apps.integrations.tasks`.
    - Web UI & HTMX Templates: Gallery and connections directory (`/integrations/connections/`), connection create & edit forms, connection detail with live HTMX connectivity test & sync triggers, and external entity mappings directory (`/integrations/references/`).
    - REST API: Endpoints under `/api/v1/integrations/` for `connections/` (with `test/`, `sync/`, `execute/` actions), `references/`, `logs/`, `zapier/hooks/`, and `zapier/sample/<event>/`.
    - Test Suite: 24 tests in `apps/integrations/tests/test_connectors.py` and 59/59 passing across all integration tests.
  - Next task: P5-06 OAuth2 provider (PKCE + client credentials) with consent screen, app registry UI, scopes; inbound webhook endpoints framework.
