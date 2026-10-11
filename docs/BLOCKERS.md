# Blockers & External Stubs
(Agent: log anything that could not be completed or that uses a fake/sandbox adapter. Format: `- [date] <task-id> <what> <what was done instead>`.)

- [2026-10-08] P1-03 Payment gateway (external live credentials) - Implemented PaymentGatewayAdapter interface with full FakePaymentGateway sandbox in `apps/billing/gateway.py` with HMAC-SHA256 signature verification, charge simulation, and webhook generation.
- [2026-10-11] P3-06 External SMTP service (live production credentials) - Implemented EmailAdapter protocol with SmtpEmailAdapter and in-memory FakeEmailAdapter sandbox in `apps/core/notifications.py` with outbox inspection and auto-detection in development/test.
