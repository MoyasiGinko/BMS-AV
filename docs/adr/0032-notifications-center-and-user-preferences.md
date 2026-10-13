# ADR 0032: Notifications Center and User Notification Preferences

## Context
Business OS generates critical operational alerts (billing invoices, approval requests, low stock warnings, security events, payroll runs). In P1-04 and P3-06, organization-level default notification channel preferences and transactional email delivery adapters were established. However, enterprise users require a centralized In-App Notifications Center, interactive topbar notifications bell, and personal user-level notification preferences allowing each team member to fine-tune alerts per channel and category without affecting fellow tenant members.

## Decision
1. **Two-Tier Notification Preference Hierarchy**:
   - Organization level (`NotificationPreference` in `apps.tenancy`): Defines tenant-wide alert policies. If disabled at the org level, the notification is skipped.
   - User level (`UserNotificationPreference` in `apps.tenancy`): Scoped to `(organization, user, category, channel)`. Allows individual users to opt-out or opt-in to specific categories per channel.
2. **Notification Primitives & Immutability**:
   - Core `Notification` (`apps.core.models`) records in-app and email dispatch events with recipient, title, body, rich `metadata` (including `action_url`, `document_type`, `document_id`), delivery status (`PENDING`, `SENT`, `FAILED`, `READ`, `SKIPPED`), and timestamps.
   - User-scoped queries guarantee users only access notifications directed to them within their active organization.
3. **In-App Notification Center UI & HTMX**:
   - Top-bar reactive bell with real-time unread badge counter and slide-out/dropdown notification preview.
   - Full-featured `/notifications/` Center with status tabs (All, Unread, Read), category filters, inline "Mark Read" / "Mark All Read" HTMX transitions, and deep document action links.
   - User preferences screen at `/notifications/preferences/` rendering a clean channel x category matrix.
4. **Additive REST API v1**:
   - Endpoints under `/api/v1/core/notifications/` with full tenant and user scoping, OpenAPI documentation, and standard error handling.

## Consequences
- Clean separation of concern: alerts can be triggered synchronously or via background tasks without UI blocking.
- Strict multi-tenant and cross-user isolation: notifications remain strictly confidential to the recipient user in the current tenant.
