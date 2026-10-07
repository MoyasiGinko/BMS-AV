# Core Module (`apps.core`)

Shared infrastructure and base runtime primitives for the Business OS multi-tenant platform.

## Responsibilities
- **Multi-Tenancy Foundation**: `TenantModel`, `TenantManager`, `TenantQuerySet`, `TenantMiddleware`, and thread/async contextvars (`tenant_context`).
- **PostgreSQL Row-Level Security (RLS)**: `enable_rls` migration helper and `app.current_org` session setter.
- **Three-Layer Authorization Engine**:
  1. *Layer 1 (Plan Entitlement)*: `has_feature_entitlement()`, `@feature_required`, `HasFeatureEntitlement`.
  2. *Layer 2 (Role Permission)*: `has_permission()`, `@permission_required`, `HasRolePermission`.
  3. *Layer 3 (Object Scope)*: `scope_queryset()`, `check_object_scope()`, `HasObjectScope`.
- **Transactional Outbox & Domain Events**: `OutboxEvent`, `events.publish()`, `events.subscribe()`, Celery outbox dispatcher.
- **Audit Logging**: `AuditLog`, `record_audit_log()`.
- **Atomic Number Sequencing**: `NumberSequence`, `generate_next_number()`.
- **DRF API Foundation (`apps.core.api`)**:
  - `TenantScopedViewSet`: Automatic organization scoping, actor injection, 3-layer permission enforcement.
  - JWT Authentication via `djangorestframework-simplejwt`.
  - RFC 7807 unified exception envelope (`code`, `message`, `details`, `request_id`).
  - `@idempotent` decorator using Redis cache with 24h replay protection.
  - Cursor & page number pagination (`StandardCursorPagination`, `StandardPageNumberPagination`).
  - Tenant rate throttles (`TenantUserRateThrottle`, `TenantAnonRateThrottle`).
  - drf-spectacular OpenAPI 3 documentation.
- **UI Components & Styleguide**:
  - 24 reusable Tailwind 4 + Alpine.js components in `templates/components/`.
  - App shell layout, auth card layout, and public layout.
  - Interactive living styleguide at `/_styleguide/`.
- **Observability**:
  - `JSONLogFormatter`: Structured JSON output with `timestamp`, `level`, `logger`, `message`, `request_id`, `organization_id`, `user_id`.
  - `SecurityHeadersMiddleware`: Permissions-Policy, nosniff, strict-origin-when-cross-origin.
  - Env-gated Sentry error tracking.
