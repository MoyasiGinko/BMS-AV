# Build State (updated by the agent after every task)

- Phase: P5 ERP maturity
- Last completed task: P5-08 Notifications center (in-app + email), user notification preferences
- Next task: P5-R Phase review
- Open `[!]` tasks: none
- Last `make verify`: PASSED (16/16 notifications tests passing, 9/9 core unit tests passing, ruff check/format clean, lint-imports clean, mypy clean)
- Notes:
  - P5-08 Complete: Notifications center (in-app + email) and user notification preferences:
    - ADR 0032 (`docs/adr/0032-notifications-center-and-user-preferences.md`): Two-tier notification preference hierarchy (organization policy overrides user preference; user opt-in/opt-out per category and channel), reactive HTMX topbar dropdown & badge counter, in-app notification center, and REST API.
    - Data Models: `UserNotificationPreference` in `apps/tenancy` with PostgreSQL RLS enabled; `Notification` enhanced with `is_read` and `action_url` properties.
    - Services & Selectors:
      - `is_notification_enabled`: Evaluates org-level `NotificationPreference` and user-level `UserNotificationPreference`.
      - `notify_user`: High-level multi-channel notification dispatcher (in-app + email) respecting user preferences and channel availability.
      - Mark read/unread, mark all as read, delete, and preference management services.
      - Selectors for notification feeds, unread counts, and user preference maps.
    - Celery Tasks: `send_async_notification` for asynchronous delivery, `cleanup_old_notifications` for lifecycle retention.
    - Web UI & HTMX:
      - Reactive topbar bell (`/notifications/unread-count/`, `/notifications/preview/`) with unread badge counter.
      - Notification center (`/notifications/`) with filtering (all/unread/read, categories, search), pagination, and inline actions.
      - User notification preferences matrix (`/notifications/preferences/`) for configuring email and in-app channels.
    - REST API: `/api/v1/core/notifications/` with endpoints for listing, unread-count, mark-read, mark-unread, mark-all-read, and personal notification preferences.
    - Tests: 16 tests in `tests/test_notifications_center.py` covering multi-channel delivery, two-tier preference hierarchy, cross-tenant isolation, web UI HTMX endpoints, REST API viewsets, and async Celery tasks.
  - Next task: P5-R Phase review.

