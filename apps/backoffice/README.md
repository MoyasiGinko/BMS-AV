# Back-Office Module (`apps.backoffice`)

## Purpose
The Back-Office module is the internal staff operations control plane for the Business OS platform. It is restricted strictly to authenticated staff and superuser operators. It provides platform-wide supervision, tenant lookup, impersonation with audit trails and sticky warning banners, subscription overrides, and outbox/webhook inspection with manual retry capabilities.

## Architecture & Security
- **Access Control**: Every endpoint requires `staff_required` (`request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)`). Non-staff users receive 403 Forbidden; unauthenticated requests redirect to login.
- **Tenant Scope**: Normal tenant users operate under PostgreSQL RLS and `TenantModel.objects`. The Back-Office control plane uses `all_tenants` unscoped queries solely within authenticated staff context.
- **Impersonation**:
  - Staff selects a tenant or user to impersonate.
  - An `AuditLog` entry is created (`backoffice.impersonate_start`).
  - Session records `impersonator_id`, `impersonator_email`, and `is_impersonating = True`.
  - An omnipresent amber warning banner is rendered across all pages (`templates/layouts/base.html`).
  - Exit button safely terminates impersonation, logs `backoffice.impersonate_stop`, and returns operator to the back-office.
- **Subscription Overrides**:
  - Staff can override plan tiers, lifecycle status, trial dates, and renewal dates.
  - A mandatory operational reason is required and recorded in `AuditLog` (`backoffice.subscription_override`).
  - Emits `billing.subscription_overridden` domain event.
- **Jobs & Webhooks**:
  - Real-time telemetry on `core.OutboxEvent` (pending, processing, processed, failed).
  - Failed events display error tracebacks with single-click immediate retry (`retry_outbox_event`).
  - Inbound webhook inspection (`billing.ProcessedWebhookEvent`).
