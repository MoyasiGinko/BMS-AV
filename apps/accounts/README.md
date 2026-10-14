# Accounts Module (`apps.accounts`)

Global identity and authentication foundation for Business OS.

## Architecture & Responsibilities
- **Global User Model (`apps.accounts.models.User`)**:
  - Independent of any single organization or tenant (tenancy is established via `tenancy.Membership`).
  - Uses email address as the primary unique username field (`USERNAME_FIELD = "email"`).
  - Normalizes and lowercases email addresses automatically upon creation.
  - Stores user preferences including locale (`locale`, default `"en"`) and time zone (`timezone`, default `"UTC"`).
  - Uniquely identifiable externally via immutable `public_id` (UUID4).
- **Authentication & Security (`django-allauth`)**:
  - Email/password authentication with configurable rate limits (`ACCOUNT_RATE_LIMITS`).
  - Two-Factor Authentication (MFA / 2FA) powered by `allauth.mfa` (TOTP / authenticator apps and recovery codes).
  - Session security with automatic rotation on authentication and HTTPS-only cookies in production.
  - Password validation enforcing length, complexity, and common password bans.
- **Back-Office Impersonation**:
  - Supports staff/superuser impersonation of end users with visual indicator banner and complete audit logging (`audit.log`).
- **Interfaces**:
  - Web UI views for sign-in, sign-up, password reset, and 2FA configuration.
  - User profile and preference settings (`/settings/profile/`).
  - Standard Django authentication backends and middleware integration.
