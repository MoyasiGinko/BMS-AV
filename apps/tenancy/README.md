# Tenancy Module (`apps.tenancy`)

Multi-tenant foundation, organization scoping, role-based access control (RBAC), invitations, and branch hierarchies for Business OS.

## Architecture & Responsibilities
- **Domain Models**:
  - `Organization`: Global tenant root entity storing company identity, base currency, fiscal calendar configurations, time zone, and system settings.
  - `Branch`: Organization-scoped business location or operating division (e.g., HQ, retail storefront, regional distribution center).
  - `Role`: Organization-scoped collection of permission strings (e.g., `sales.read`, `inventory.manage`, `accounting.post`). Built-in system roles include `Owner`, `Admin`, `Manager`, and `Member`.
  - `Membership`: Join table linking global users (`accounts.User`) to organizations with an assigned `Role`, default `Branch`, and active state.
  - `Invitation`: Cryptographically secure tenant invitation tokens with expiration, recipient email verification, and automated membership activation upon acceptance.
- **Tenancy Scoping & Isolation Architecture**:
  - `TenantModel` base class: Enforces foreign key to `Organization` and UUIDv7 `public_id`.
  - `TenantManager` / `TenantQuerySet`: Automatic queryset filtering by current tenant context (`for_tenant(org)`).
  - PostgreSQL Row-Level Security (RLS): Database-level safety net enforcing `organization_id = current_setting('app.current_tenant_id')` across all tenant tables.
  - `TenantMiddleware`: Extracts active organization from request subdomain, headers (`X-Organization-ID`), or user session context.
- **Services & Selectors**:
  - `services.create_organization`: Atomic provisioning creating organization, default branches, system roles, owner membership, chart of accounts seed, and trial subscription.
  - `services.invite_user` & `services.accept_invitation`: Secure onboarding workflow.
  - `selectors.get_user_organizations`: Retrieves all organizations accessible to a user.
- **Interfaces**:
  - UI screens for organization management, switcher dropdown, member management, branch administration, and role permissions editor (`/tenancy/`, `/settings/members/`, `/settings/branches/`, `/settings/roles/`).
  - REST API v1 (`/api/v1/tenancy/organizations/`, `/memberships/`, `/branches/`, `/roles/`, `/invitations/`).
