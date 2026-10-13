# ADR 0029: Integration Connector Framework & External Reference Architecture

## Context
Task P5-05 requires an enterprise integration connector framework:
1. **Connector Registry & Base Interface**: Extensible plug-and-play architecture for third-party and standard external integrations.
2. **Encrypted Connection State**: `IntegrationConnection` storing connector-specific configurations and credentials encrypted at rest using symmetric Fernet (`apps.core.crypto`).
3. **External References**: `ExternalReference` bidirectional mapping internal domain entity identifiers (customers, products, invoices, orders) to external system identifiers with unique constraints per tenant and connection.
4. **Synchronization Logging**: `IntegrationSyncLog` capturing structured execution history, duration, direction (inbound/outbound), processed/succeeded/failed counts, and error details.
5. **Built-in Connectors**:
   - `generic_rest`: Configurable HTTP endpoint calls with authentication headers, payload templates, and field mapping.
   - `csv_import`: Automated batch CSV data ingestion linking to entity import pipelines.
   - `fake_payments`: Sandbox payment processor supporting payment charges, refunds, and external reference recording.
   - `fake_sms`: Sandbox SMS communications provider with in-memory delivery audit outbox.
   - `smtp_email`: Custom SMTP configuration per tenant with connection health verification and email dispatch.
   - `zapier_compat`: Zapier REST hooks compatibility layer with subscription endpoints, unsubscribe hooks, and trigger sample data.
6. **Web UI & REST API**: Server-rendered HTMX dashboards at `/integrations/connections/` and REST endpoints under `/api/v1/integrations/`.

## Decision
1. **Data Models (`apps/integrations/models.py`)**:
   - `IntegrationConnection`: Inherits `TenantModel`, UUIDv7 `public_id`, `name`, `connector_type`, `status` (`active`, `inactive`, `error`, `testing`), `config` (JSONField for endpoint URLs, mappings, options), `encrypted_credentials` (TextField for Fernet-encrypted secrets with property accessor `credentials`), `sync_interval_minutes`, `last_synced_at`, `last_error`.
   - `ExternalReference`: Inherits `TenantModel`, `connection` FK, `entity_type` (e.g. `customer`, `product`, `invoice`), `internal_id`, `external_id`, `metadata` (JSONField). Unique constraint on `[organization, connection, entity_type, external_id]`.
   - `IntegrationSyncLog`: Inherits `TenantModel`, `connection` FK, `direction` (`inbound`, `outbound`), `status` (`success`, `failed`, `partial`), `action`, `records_processed`, `records_succeeded`, `records_failed`, `error_details`, `duration_ms`.
   - RLS enabled on all new integration tables.

2. **Registry & Connector Abstraction (`apps/integrations/connectors/`)**:
   - `BaseConnector`: Abstract base class defining `connector_type`, `name`, `config_schema`, `test_connection(connection)`, `sync(connection, direction, params)`, and `execute_action(connection, action, payload)`.
   - `ConnectorRegistry`: Singleton registry discovering and registering connector implementations.
   - Standard connectors: `GenericRestConnector`, `CsvImportConnector`, `FakePaymentsConnector`, `FakeSmsConnector`, `SmtpEmailConnector`, and `ZapierCompatConnector`.

3. **Security & Credentials**:
   - Credentials (API tokens, secret keys, passwords) are encrypted before persisting to DB via `apps.core.crypto.encrypt_value`.
   - REST API serializers mask or exclude sensitive credentials on serialization.

4. **Web UI & REST API**:
   - Web views: Gallery of connectors, connection create/edit forms, test connection HTMX buttons, manual sync trigger, and sync logs table.
   - REST API: Endpoints under `/api/v1/integrations/connections/`, `/references/`, `/logs/`, and `/zapier/hooks/`.

## Consequences
- Enables standard, secure external system connectivity across ERP domains without ad-hoc scripts.
- Guarantees strict multi-tenant isolation, encrypted secrets, and complete operational sync auditability.
