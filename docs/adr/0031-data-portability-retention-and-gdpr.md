# 0031. Data Portability, Data Retention, and GDPR Privacy Workflows

Date: 2026-10-14

## Context
Enterprise and SaaS compliance mandates robust data portability, automated data lifecycle retention, and GDPR/CCPA data subject rights (Articles 15 SAR, 17 Erasure, and 20 Portability). In a multi-tenant ERP platform:
1. Full-tenant data portability requires exporting and importing tenant state across catalog, CRM, sales, accounting, inventory, and HR while strictly preserving tenant boundaries.
2. Financial auditability requires that posted financial journals, tax invoices, and statutory audit trails must never be deleted; right-to-erasure requests must pseudonymize/anonymize PII without violating ledger and accounting invariants.
3. High-volume ephemeral records (webhook delivery logs, inbound logs, sync logs, temporary export files) must be pruned per tenant-configured retention windows to avoid database bloat and compliance liability.

## Decision
1. **Full-Tenant Export & Import (`TenantExportJob`, `TenantImportJob`)**:
   - Built under `apps.integrations` at the top architectural layer.
   - Tenant export generates a compressed ZIP bundle containing `manifest.json` (schema version, checksum, tenant metadata) and domain-grouped JSON files. Executed asynchronously via Celery.
   - Tenant import validates package schema, inspects dependencies, checks tenant isolation, and commits records strictly assigned to the target tenant.
2. **Data Retention Policies (`DataRetentionPolicy`)**:
   - Tenant-scoped settings configuring retention periods for audit logs, webhook logs, sync logs, and export artifacts.
   - Periodic Celery task (`enforce_data_retention_policies_task`) and on-demand trigger to purge records older than the configured threshold.
3. **GDPR Data Subject Requests (`DataSubjectRequest`)**:
   - Supports Access/Export (Article 15 & 20) and Erasure (Article 17).
   - Erasure workflow executes compliant pseudonymization: customer and contact PII is replaced with anonymized tokens, non-financial notes and marketing preferences are wiped, while financial ledger lines, invoices, and payment records remain intact.
4. **Security & Isolation**:
   - All models inherit `TenantModel` and have PostgreSQL Row-Level Security (RLS) enabled.
   - Downloadable export files are stored with random UUID filenames and served only through authenticated, tenant-scoped permission-checked views.

## Consequences
- Complete compliance with data portability, retention limits, and privacy regulations.
- Accounting invariants and historical financial integrity are protected against destructive deletion.
- Log pruning keeps database indexes lean and query performance high.
