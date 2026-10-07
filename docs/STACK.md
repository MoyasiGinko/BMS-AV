# Technology Stack (versions verified against PyPI / npm / postgresql.org on 2026-10-07)

**Policy**: use exactly this stack. Pin through `uv.lock` (run `uv lock` once in P0-01 and commit it). Never downgrade or swap a package without an ADR.
If a listed package breaks on Django 6.1 at runtime, first check for a newer release, then use the fallback in the last column; only as a last resort fall back the
whole project to Django 6.0.9 (security fixes until April 2027), with an ADR.

## Runtime & infrastructure
| Component | Version | Notes |
|---|---|---|
| Python | **3.14** (`.python-version`); code must also run on 3.13 | Django 6.1 supports 3.12-3.14. Use `uuid.uuid7()` for `public_id` (time-ordered). |
| PostgreSQL | **18** (`postgres:18` image, 18.6 current minor) | PG 19 is releasing this month; stay on 18 until 19.1. Use native JSONB, partial/composite indexes, RLS. |
| Redis | **8** (`redis:8`) | Celery broker/result, cache (Django built-in `RedisCache`), rate limits. Valkey 8/9 is a drop-in alternative. |
| uv | 0.12.x | Package/venv manager (`uv sync`, `uv run`, `uv lock`). Falls back to pip if absent. |
| Docker / Compose | current | db + redis for dev; full prod compose in P7-03. |
| Node | **not required** | Tailwind via standalone CLI (django-tailwind-cli); JS libs vendored by `scripts/vendor_frontend.sh`. Node only for the optional Context7 MCP. |

## Python packages (runtime)
| Package | Version | Purpose | Notes / fallback |
|---|---|---|---|
| Django | **6.1.2** | Full-stack framework | 6.1 released 2026-08-05; non-LTS (next LTS is 6.2, April 2027). |
| psycopg[binary,pool] | 3.3.6 | PostgreSQL driver + pooling | Use `OPTIONS: {"pool": True}` |
| django-environ | 0.14.0 | Typed env settings | |
| whitenoise | 6.12.0 | Static files | |
| gunicorn | 26.2.0 | WSGI server | |
| djangorestframework | 3.18.3 | REST API (additive layer) | declares Django 6.1 support |
| drf-spectacular | 0.30.0 | OpenAPI 3 schema + docs | |
| django-filter | 26.2 | API/list filtering | declares 6.1 support |
| djangorestframework-simplejwt | 5.5.1 | JWT for first-party clients | |
| django-oauth-toolkit | 3.4.1 | OAuth2 provider (PKCE, client credentials) | |
| django-cors-headers | 4.9.0 | CORS for API | |
| django-allauth[mfa] | 65.19.7 | Auth, email verification, TOTP/WebAuthn MFA | declares 6.1 support; replaces django-otp |
| django-axes | 8.3.1 | Login throttling/lockout | |
| cryptography | 50.0.2 | Field-level encryption (Fernet/AES-GCM) | |
| django-htmx | 1.29.0 | `request.htmx`, HTMX middleware | declares 6.1 support |
| django-tailwind-cli | 4.8.1 | Manages Tailwind standalone CLI (no Node) | set `TAILWIND_CLI_VERSION = "4.3.3"` |
| celery[redis] | 5.6.3 | Background jobs + beat | Schedules defined in code (`CELERY_BEAT_SCHEDULE`); DB-driven schedules via a polling task (django-celery-beat does not support Django 6.1 yet) |
| redis (client) | 8.1.0 | Redis client | |
| django-treebeard | 7.0.2 | Hierarchical data (chart of accounts, categories, org units) | declares 6.1 support |
| django-countries | 9.1.0 | Country fields | |
| django-phonenumber-field[phonenumbers] | 8.5.0 | Phone fields/validation | |
| babel | 2.18.0 | Currency/number/date formatting per org locale | |
| pydantic | 2.13.5 | Validation of automation conditions, AI tool schemas, webhook payloads | |
| orjson | 3.12.0 | Fast JSON for events/webhooks | |
| django-waffle | 5.0.0 | Feature flags (separate from plan entitlements) | |
| openpyxl | 3.1.5 | XLSX import/export | |
| reportlab | 5.0.1 | PDF documents (invoices, payslips, reports) | |
| pillow | 12.3.0 | Images | |
| qrcode | 8.2 | QR codes (payments, receipts) | |
| django-storages[s3] | 1.14.6 | S3-compatible media storage | |
| sentry-sdk | 2.71.0 | Error tracking (env-gated) | |
| structlog | 26.1.0 | Structured JSON logging | |
| prometheus-client | 0.26.0 | `/metrics` endpoint (django-prometheus lacks Django 6.1 support) | |
| django-health-check | 4.8.0 | Health/readiness checks | declares 6.1 support |

Optional extra `ai`: anthropic 1.11.0, openai 3.26.0, google-genai 2.28.0 (provider adapters; default provider is a deterministic fake).

## Dev / quality
pytest 9.1.1, pytest-django 4.14.0, pytest-cov 7.1.0, pytest-xdist 3.8.0, pytest-randomly 5.0.0, factory-boy 3.3.3, hypothesis 6.168.5, freezegun 1.5.5,
responses 0.26.3, ruff 0.16.10, mypy 2.4.0, django-stubs 6.1.2, djangorestframework-stubs 3.18.1, celery-types 0.26.0, import-linter 2.15,
pip-audit 2.10.1, pre-commit 4.6.2, playwright 1.63.0 + pytest-playwright 0.9.0, django-debug-toolbar 8.0.0, django-extensions 4.1.

## Frontend (vendored into `static/vendor/` by `scripts/vendor_frontend.sh`, no CDN at runtime)
| Library | Version | Purpose |
|---|---|---|
| Tailwind CSS | **4.3.3** | CSS-first config (`@import "tailwindcss"; @theme {...}`), no tailwind.config.js |
| HTMX | 2.0.11 | Partial updates (`htmx.org`) |
| Alpine.js | 3.17.4 (+ focus, collapse plugins) | Small client state |
| Chart.js | 4.5.1 | Charts |
| Lucide | 1.52.0 | Icons (SVG sprite) |
| SortableJS | 1.15.7 | Kanban/drag lists |

## Django 6.x features to USE (read official docs for exact APIs)
- **Template partials** (`{% partialdef %}` / `{% partial %}`, `template.html#name`): HTMX fragments live in the same template file as the page. Do not create separate `_fragment.html` files or add django-cotton.
- **Built-in CSP** (`ContentSecurityPolicyMiddleware`, `SECURE_CSP`, nonce via context processor): do NOT install django-csp.
- **Field fetch modes (6.1)**: run tests with the raise/peek fetch mode so accidental N+1 queries fail fast; keep `select_related/prefetch_related` in selectors.
- **Database-level `on_delete` options (6.1)** where cascades are safe; business records are never deleted anyway.
- **`MAILERS` setting (6.1)** for multiple named email backends (transactional vs notifications vs fake in dev/test). Do not use legacy `EMAIL_*` settings.
- **Built-in `django.tasks`** interface exists, but production background work stays on Celery (queues, retries, beat).
- Built-in `RedisCache` backend for cache (no django-redis).
- Python 3.14: `uuid.uuid7()`, deferred annotation evaluation; PostgreSQL 18: `uuidv7()`, virtual generated columns.

## Resolution proof
`docs/resolved-versions-2026-10-07.txt` is the full transitive set that resolved cleanly (uv, Python 3.14) with Django 6.1.2. Two packages were dropped because they cap Django below 6.1: django-celery-beat (2.9.0: Django<6.1) and django-prometheus (2.5.0: Django<6.1).

## Version check automation
`make deps-check` runs `uv lock --check`, `pip check`, `pip-audit`, and `python -W error::DeprecationWarning manage.py check`. `/verify` runs it.
