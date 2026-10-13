# Integrations & Connectors Module

## Purpose
The `apps.integrations` module provides an enterprise-grade integration, connector, and data governance framework:
1. **Validate-Preview-Commit Imports**: Safe, multi-step bulk data import for products catalog, customer directory, and future entities (CSV and XLSX).
   - **Upload & Validate**: Parses input files, normalizes headers, validates schemas, types, and constraints without touching the database.
   - **Preview & Inspect**: Interactive UI showing summary metrics, valid rows sample, and detailed row-level error reports.
   - **Commit**: Transactional commit into domain services (`apps.catalog.services`, `apps.customers.services`), tracking created/updated/skipped counts and publishing domain events.
2. **Entity Data Exports**: Background generation of CSV (RFC 4180 with utf-8-sig BOM) and XLSX (`openpyxl`) files for operational datasets.
3. **Template Engine**: Dynamic generation of official CSV and XLSX templates pre-populated with column headers and sample data.
4. **Connector Framework (P5-05)**: Pluggable connector registry supporting external systems:
   - Built-in connectors: `generic_rest`, `csv_import`, `fake_payments`, `fake_sms`, `smtp_email`, `zapier_compat`.
   - Encrypted credentials storage with fernet-based envelope encryption.
   - Transactional synchronization logging and external entity cross-referencing.
5. **OAuth2 Provider & Inbound Webhooks (P5-06)**:
   - Standards-compliant OAuth2 provider supporting Authorization Code Grant with PKCE and Client Credentials.
   - Configurable scopes (`read:catalog`, `write:sales`, `read:reports`, `admin`).
   - Tenant-scoped Inbound Webhook Endpoints with HMAC signature verification and transactional dispatching.
6. **Full-Tenant Data Portability & GDPR Compliance (P5-07)**:
   - Full tenant export/import archive format (ZIP manifest with scoped JSON datasets) with SHA-256 integrity check.
   - Automated retention policies for logs, webhooks, and audit trails.
   - GDPR Data Subject Requests (access export and erasure workflows with customer pseudonymization while maintaining immutable financial ledgers).

## Models
- `ImportJob(TenantModel)`: Bulk entity import lifecycle management.
- `ExportJob(TenantModel)`: Background tabular file export tracking.
- `IntegrationConnection(TenantModel)`: Connector instances with encrypted credentials.
- `ExternalReference(TenantModel)`: Mapping between local entity IDs and remote third-party IDs.
- `SyncLog(TenantModel)`: Audit log of external sync operations.
- `OAuthApplication(TenantModel)`: Registered OAuth2 client applications with PKCE support.
- `OAuthAuthorizationCode(TenantModel)`: Short-lived authorization codes with PKCE code challenges.
- `OAuthAccessToken(TenantModel)`: Scoped access tokens and refresh tokens.
- `InboundWebhookEndpoint(TenantModel)`: Inbound webhook listener configurations with HMAC secret tokens.
- `TenantExportJob(TenantModel)`: Full tenant archive export jobs.
- `TenantImportJob(TenantModel)`: Full tenant archive import jobs.
- `DataRetentionPolicy(TenantModel)`: Configurable retention periods per data category.
- `DataSubjectRequest(TenantModel)`: GDPR data subject access and erasure requests.

All models enforce PostgreSQL Row-Level Security (RLS) policies.

## Architecture
- Layered in the top application tier (`apps.reports | apps.ai_assistant | apps.automation | apps.integrations`).
- Strict tenant boundary isolation enforced on all views, viewsets, services, and Celery tasks.
