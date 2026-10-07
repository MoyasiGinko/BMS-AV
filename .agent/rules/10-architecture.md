---
trigger: always_on
---
# Architecture Rules (always on)

- Modular monolith. Apps under `apps/<name>/`. Shared infrastructure in `apps/core/` (including `apps/core/api/` for DRF base classes).
- Per app layout: `models.py  services.py  selectors.py  events.py  permissions.py  forms.py  views.py  urls.py  tasks.py  admin.py
  api/{serializers,views,urls,filters}.py  templates/<app>/  tests/`.
- `services.py`: all writes. Keyword-only args, explicit `actor`, `@transaction.atomic`, row locks (`select_for_update`) on stock,
  balances and document status, then `events.publish(...)`.
- `selectors.py`: all reads/reporting queries. Always `select_related/prefetch_related`; no N+1 (tests use `django_assert_max_num_queries`).
- Views and DRF viewsets are thin: parse input -> call service/selector -> render/serialize. No ORM writes in views.
- Document status machines are declared once per model (`ALLOWED_TRANSITIONS`) and enforced in the service.
- Cross-module reactions that would invert the layer order use domain events (`apps.core.events.publish`) consumed by handlers.
- Import contracts live in `pyproject.toml`; if `lint-imports` fails, restructure (move code down a layer or use an event). Never relax
  the contract.
- Every model: UUID `public_id` for external exposure, `created_at/updated_at/created_by`, explicit `related_name`,
  constraints in `Meta.constraints`, `__str__`.
- Settings split: `config/settings/{base,dev,test,prod,prod_check}.py`. Typed env parsing via django-environ. No secrets in code.
- i18n from day one: wrap user-visible strings in `gettext`; org-level timezone/currency/date format.

## Stack & modern Django (see docs/STACK.md for exact versions)
- Django 6.1 / Python 3.14 / PostgreSQL 18. Use `uuid.uuid7()` for `public_id`. Use Django 6.x features: template partials, built-in CSP, field fetch modes
  (tests run with the raise mode to catch N+1), `MAILERS`, DB-level `on_delete` where safe. Consult the official Django 6.1 docs for exact APIs.
- Do NOT add: django-csp, django-redis, django-celery-beat, django-prometheus, django-otp, django-cotton (replaced by built-ins or incompatible with Django 6.1).
- Celery stays the background engine; DB-driven schedules (report schedules, recurring invoices) are handled by one periodic "dispatch due schedules" task.
- Any new dependency needs an ADR (why, maintenance status, Django 6.1 compatibility) and must pass `make deps-check`.
