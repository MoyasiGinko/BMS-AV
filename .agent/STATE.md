# Build State (updated by the agent after every task)

- Phase: P3 Growth bundle: Purchasing + full Accounting
- Last completed task: P3-06
- Next task: P3-07
- Open `[!]` tasks: none
- Last `make verify`: PASSED (58/58 tests in sales and notifications pass, ruff check/format clean, django system check clean, openapi validated with fail-on-warn, import-linter contracts 2 kept / 0 broken)
- Notes:
  - P3-06 Recurring invoices, payment reminders, and notification framework completed:
    - Notification email framework in `apps/core/notifications.py` with `EmailAdapter` protocol, `SmtpEmailAdapter`, and in-memory `FakeEmailAdapter` sandbox.
    - `Notification` model with channels (email, in-app, sms, webhook) and statuses (pending, sent, failed, read, skipped).
    - `RecurringInvoiceProfile` & `RecurringInvoiceLine` models with flexible recurrence frequencies, intervals, cycle limits, auto-posting, and email delivery.
    - `PaymentReminderRule` & `PaymentReminderLog` models with configurable timing stages, template string interpolation, and duplicate delivery suppression.
    - Celery beat tasks `sales.process_due_recurring_invoices` and `sales.dispatch_due_payment_reminders` registered in `CELERY_BEAT_SCHEDULE`.
    - Server-rendered HTMX screens: recurring invoice list, detail, create/edit form, and payment reminder rules/dashboard.
    - Versioned DRF REST API endpoints under `/api/v1/sales/recurring-invoices/`, `/payment-reminders/rules/`, and `/payment-reminders/logs/` with OpenAPI validation.
    - Unit, integration, cross-tenant isolation, and state machine tests (15 new tests, 58 total in suite passing).
  - Next task: P3-07 seed_demo for "growing company" + invariants suite complete (AR/AP/inventory subledgers vs control accounts).
