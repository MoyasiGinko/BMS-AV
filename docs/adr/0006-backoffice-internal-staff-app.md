# ADR 0006: Back-Office Internal Staff App Architecture
Status: accepted | Date: 2026-10-08
Context: Backlog task P1-07 specifies an internal staff application for tenant lookup, impersonation with audit and persistent warning banner, subscription overrides, and job/webhook inspection.
Decision: Create `apps.backoffice` as the internal operations control plane accessible strictly to authenticated staff (`is_staff` or `is_superuser`). Impersonation switches session user context while preserving `request.session['impersonator_id']` and rendering an omnipresent top warning banner across all layouts, with every session start, stop, override, and retry recorded in `AuditLog`.
Consequences: Multi-tenant boundaries are strictly respected during normal operation; internal operators can inspect any tenant through `all_tenants` queries only within the authenticated staff control plane.
