# ADR 0039: Security Pass: Tenant Isolation, Rate Limiting, CSP, Secrets Handling, and Deployment Hardening

## Context
A multi-tenant SaaS Business Management Platform (ERP) handles mission-critical financial, human resources, inventory, and customer data across isolated business organizations. Ensuring cross-tenant boundary integrity, protection against brute-force attacks, robust HTTP security headers, leak-proof observability, and vulnerability-free dependencies is non-negotiable before production readiness.

## Decision
1. **Multi-Tenant Defense-in-Depth & Isolation Audit**:
   - Every domain tenant model inherits from `apps.core.models.TenantModel` and uses `apps.core.models.TenantManager` auto-scoped to the active request/task organization.
   - Defense-in-depth enforced via PostgreSQL Row-Level Security (`ENABLE ROW LEVEL SECURITY; FORCE ROW LEVEL SECURITY;`) using session-scoped `current_setting('app.current_org')`.
   - Comprehensive cross-tenant isolation test suites verified across all 19 domain applications (tenancy, billing, catalog, inventory, customers, sales, purchasing, accounting, pos, crm, hr, payroll, approvals, integrations, automation, ai_assistant, reports) preventing cross-organization read, write, update, delete, export, or task execution.

2. **Content Security Policy (CSP) & HTTP Security Headers**:
   - Leveraged Django 6.1 built-in `django.middleware.csp.ContentSecurityPolicyMiddleware` with strict directives:
     - `default-src 'self'`
     - `frame-ancestors 'none'` (mitigating UI redress/clickjacking attacks)
     - `object-src 'none'` (disabling Flash/Java plugins)
     - `base-uri 'self'` and `form-action 'self'`
     - `script-src` and `style-src` scoped to `'self'` and `'unsafe-inline'` for HTMX and Alpine.js execution.
   - Enforced HTTP security headers via `SecurityHeadersMiddleware`:
     - `X-Content-Type-Options: nosniff`
     - `Referrer-Policy: strict-origin-when-cross-origin`
     - `Permissions-Policy: accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()`

3. **Dynamic Multi-Tier Rate Limiting**:
   - **REST API Throttling**:
     - `TenantScopedViewSet` enforces `[TenantUserRateThrottle, TenantAnonRateThrottle, ApiKeyRateThrottle]`.
     - `ApiKeyRateThrottle` resolves rate limits dynamically from the tenant organization's active subscription tier (e.g. Starter: 60/min, Growth: 300/min, Business: 1200/min, Enterprise: 3000/min).
     - `TenantUserRateThrottle` automatically defers API key requests to prevent throttle collisions.
   - **Web Authentication Throttling**:
     - Explicitly configured `ACCOUNT_RATE_LIMITS` for `django-allauth` (`login`, `login_failed`, `signup`, `reset_password`, `change_password`, `manage_email`) to thwart credential stuffing and brute-force attacks.

4. **Secrets Handling & Log Sanitization**:
   - Field-level encryption implemented via `cryptography.fernet.Fernet` (`apps.core.crypto.encrypt_value`) derived from `FIELD_ENCRYPTION_KEY` for sensitive HR fields (national IDs, bank account numbers) and external integration connection tokens/credentials.
   - API Keys stored as irreversible salted cryptographic hashes (`PBKDF2/SHA256`) with prefix-based lookup; raw secret revealed only once upon creation/rotation.
   - Added recursive sensitive key scrubbing in `apps.core.logging.JSONLogFormatter` masking passwords, secrets, tokens, API keys, credentials, cookies, and sensitive PII to `***REDACTED***` in all structured logs.

5. **Vulnerability Audit & Deployment Checks**:
   - Audited dependencies via `pip-audit`, confirming zero known CVEs or vulnerable packages.
   - Verified Django production deployment readiness via `python manage.py check --deploy --settings=config.settings.prod_check`, confirming 0 warnings and 0 errors.

## Consequences
- Tenant data isolation is fortified across both application logic and database engine levels.
- External API abuse and credential stuffing are stopped via layered rate limits.
- Sensitive credentials and PII remain encrypted at rest and cannot leak into structured logs.
- All HTTP responses deliver modern security headers and strict CSP.
