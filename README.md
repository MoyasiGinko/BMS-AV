# Business OS: Multi-Tenant SaaS ERP & Business Management Platform

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![Django 6.1](https://img.shields.io/badge/django-6.1-green.svg)](https://docs.djangoproject.com/)
[![PostgreSQL 18](https://img.shields.io/badge/postgresql-18-blue.svg)](https://www.postgresql.org/)
[![Redis 8](https://img.shields.io/badge/redis-8-red.svg)](https://redis.io/)
[![HTMX 2](https://img.shields.io/badge/HTMX-2.0-blueviolet.svg)](https://htmx.org/)
[![Tailwind 4](https://img.shields.io/badge/tailwind-4.0-cyan.svg)](https://tailwindcss.com/)
[![CI / Quality Gate](https://img.shields.io/badge/gate-make%20verify%20%7C%20PASSED-success.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An enterprise-grade, multi-tenant SaaS Business Management Platform (ERP) built with a modern, high-performance Django full-stack architecture. Server-rendered templates, HTMX 2, Alpine.js 3, and Tailwind CSS 4 deliver a responsive, reactive single-page feel without single-page app complexity, coupled with a versioned Django REST Framework (DRF) API, OAuth2 authorization server, and transactional outbox webhooks.

---

## 🌟 Key Features & Functional Modules

| Module | Purpose & Core Capabilities |
|---|---|
| **[Core](apps/core/)** | Shared base models (`TenantModel`), audit logging, cryptography, JSON log sanitization, event catalog, and system health checks (`/healthz`, `/readyz`). |
| **[Tenancy](apps/tenancy/)** | Multi-tenant isolation, organization roots, branches, RBAC roles & permissions, team member invitations, and PostgreSQL Row-Level Security (RLS). |
| **[Billing](apps/billing/)** | Subscription tier management (`Starter`, `Growth`, `Business`, `Enterprise`), entitlement enforcement, feature gates, usage metering, and mock payment adapters. |
| **[Accounting](apps/accounting/)** | General ledger, chart of accounts, automated journal entries, strict double-entry balance check constraints, period closing, and reversing audit trails. |
| **[Catalog](apps/catalog/)** | Product catalog, SKU management, multi-tier pricing, product variants, categories, and units of measure. |
| **[Customers](apps/customers/)** | Customer directory, credit limits, payment terms, multiple addresses, and contact hierarchies. |
| **[Sales](apps/sales/)** | End-to-end sales lifecycle: quotes, sales orders, tax calculations, invoice posting, customer payments, partial allocations, recurring invoices, and reminder rules. |
| **[Purchasing](apps/purchasing/)** | Vendor management, purchase orders, goods receipt notes, 3-way matching, and accounts payable bill posting. |
| **[Inventory](apps/inventory/)** | Multi-warehouse inventory control, real-time stock levels, inter-warehouse transfers, lot/batch tracking, reorder alerts, and physical stocktaking adjustments. |
| **[Point of Sale (POS)](apps/pos/)** | High-velocity retail register sessions, opening/closing cash counts, barcode scanning, thermal receipt printing, and offline PWA caching. |
| **[CRM](apps/crm/)** | Customer relationship management, lead capture, deal pipeline tracking with drag-and-drop Kanban, and interaction histories. |
| **[HR](apps/hr/)** | Employee directory, department structures, job titles, and compensation package configurations. |
| **[Payroll](apps/payroll/)** | Salary component rules (allowances, deductions, taxes), automated payroll execution runs, payslip generation, and GL salary disbursement entries. |
| **[Approvals](apps/approvals/)** | Multi-step approval chains and threshold policies for high-value purchase orders, expense claims, and credit overrides. |
| **[Automation](apps/automation/)** | Trigger-action workflow engine responding to internal domain events with conditional branching and automated webhook/email actions. |
| **[Reports](apps/reports/)** | Financial statements (Balance Sheet, Trial Balance, P&L), ABC inventory analysis, customer cohort retention, and scheduled background export jobs. |
| **[AI Assistant](apps/ai_assistant/)** | Conversational business intelligence, safe read-only SQL generation, natural language document drafting, and executive metric summaries. |
| **[Integrations](apps/integrations/)** | Inbound/outbound webhooks with HMAC-SHA256 signature verification, API keys, OAuth 2.0 PKCE / Client Credentials, and connector adapters. |
| **[Back-Office](apps/backoffice/)** | Superuser administration portal: tenant provisioning, plan overrides, usage monitoring, and staff impersonation with visual banners and audit logs. |

---

## 🏗️ Architecture & Technical Stack

- **Backend**: Python 3.14, Django 6.1, Gunicorn WSGI.
- **Database**: PostgreSQL 18 with enforced Row-Level Security (RLS) on all tenant tables.
- **Cache & Async Queue**: Redis 8 + Celery 5.6 for background task execution and scheduled jobs.
- **Frontend**: Django Template Partials + HTMX 2.0 + Alpine.js 3 + Tailwind CSS 4 (compiled via standalone binary, zero Node.js runtime dependency).
- **Package Management**: `uv` for deterministic, sub-second dependency resolution.
- **Security & Hardening**:
  - Django 6.1 built-in Content Security Policy (CSP) with strict directives.
  - Symmetrical AES-128 Fernet encryption for secrets stored at rest.
  - Multi-tier dynamic rate limiting (`ApiKeyRateThrottle`).
  - Zero-leakage structured JSON logging with recursive PII/credential redaction.
  - Two-Factor Authentication (MFA / 2FA) via `django-allauth`.

---

## 🔑 Demo Login Credentials

The platform includes pre-seeded, multi-role demo accounts with realistic historical ledgers, stock, POS registers, and employee workflows. All demo accounts use the standard password **`demo12345`**.

- **Live Railway Deployment**: [https://bms-av-production.up.railway.app/accounts/login/](https://bms-av-production.up.railway.app/accounts/login/)
- **Local Development**: [http://localhost:8000/accounts/login/](http://localhost:8000/accounts/login/)

### 👑 Platform Superadmin & Back-Office Control Plane
*Global administrative access (`is_staff=True`, `is_superuser=True`) across all tenants, back-office operations, and Django administration.*

| Role | Email Address | Password | Capabilities & Direct Links |
|---|---|---|---|
| **Superadmin** | `admin@businessos.com` | `demo12345` | Access to the internal **[Back-Office](/backoffice/)** portal (tenant provisioning, subscription overrides, staff impersonation, audit logs) and **[Django Admin](/admin/)**. |

> **Tip**: You can also provision custom superuser accounts locally anytime via `uv run python manage.py createsuperuser`.

### 1. Small Shop: **Artisan Bakery & Cafe** (`slug: small-shop`)
*Plan: **Starter** | Focus: High-velocity POS counter checkouts, retail inventory, cash/card split tenders, and customer invoicing.*

| Role | Email Address | Password | Capabilities & Access |
|---|---|---|---|
| **Owner** | `owner@artisanbakery.com` | `demo12345` | Full administrative control, billing, team management, and executive reports. |
| **Store Manager** | `manager@artisanbakery.com` | `demo12345` | Product catalog, pricing adjustments, inventory restocks, and daily sales auditing. |
| **Cashier** | `cashier@artisanbakery.com` | `demo12345` | POS register sessions ("Front Counter 1"), barcode scanning, order lookup, and receipts. |
| **Accountant** | `accountant@artisanbakery.com` | `demo12345` | General ledger, journal entries, tax reporting, and customer payment allocations. |

### 2. Growing Company: **Apex Industrial Wholesale** (`slug: growing-company`)
*Plan: **Growth** | Focus: Multi-warehouse logistics, B2B purchasing & 3-way matching, quotes & recurring billing, CRM pipeline, and HR/Payroll.*

| Role | Email Address | Password | Capabilities & Access |
|---|---|---|---|
| **Owner / CEO** | `owner@apexwholesale.com` | `demo12345` | Complete company-wide visibility across all branches, warehouses, and financial books. |
| **Sales Manager** | `sales@apexwholesale.com` | `demo12345` | CRM leads, drag-and-drop deal pipeline, sales quotes, and customer accounts. |
| **Procurement / Buyer**| `buyer@apexwholesale.com` | `demo12345` | Vendor management, purchase orders, goods receipts, and accounts payable bills. |
| **Senior Accountant** | `accountant@apexwholesale.com` | `demo12345` | Balance sheet, P&L, trial balance, bank reconciliation, and recurring billing rules. |
| **Warehouse Manager** | `warehouse@apexwholesale.com` | `demo12345` | Multi-warehouse stock transfers, lot/batch tracking, adjustments, and reorder levels. |

---

## 🚀 Quickstart Guide

### Prerequisites
- Python 3.14
- `uv` package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `winget install astral-sh.uv`)
- PostgreSQL 18 & Redis 8 (running locally or via Docker)

### 1. Local Development Setup
```bash
# Clone the repository
git clone https://github.com/MoyasiGinko/BMS-AV.git
cd BMS-AV

# Set up environment variables
cp .env.example .env

# Install dependencies and sync virtual environment
uv sync

# Run database migrations
uv run python manage.py migrate

# Seed demo data (both demo organizations, products, stock, invoices, employees)
uv run python manage.py seed_demo

# Start local development server
uv run python manage.py runserver
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### 2. Starting the Celery Background Worker
```bash
uv run celery -A config worker --loglevel=info
```

### 3. Production Deployment with Docker Compose
```bash
# Configure production secrets
cp .env.example .env
# Edit .env with your production DB credentials, domain, and secret keys

# Build and start all 6 production services in detached mode
docker compose -f docker-compose.prod.yml up -d --build

# Verify container health
docker compose -f docker-compose.prod.yml ps
```

The production topology launches:
1. `web`: Gunicorn WSGI server running Django with non-root UID 10001.
2. `worker`: Celery asynchronous task processor.
3. `beat`: Celery beat periodic schedule dispatcher.
4. `db`: PostgreSQL 18 with persistent volume.
5. `redis`: Redis 8 in-memory store.
6. `caddy`: Caddy 2 reverse proxy with automatic HTTPS and HTTP/3 QUIC.

---

## 🛠️ Developer Command Reference

| Command | Action |
|---|---|
| `make setup` | Sync dependencies via uv, initialize database, and run migrations. |
| `make verify` | **The Quality Gate**: executes linting, formatting checks, type validation, migration dry-runs, architecture constraint checks, unit/integration tests, and security deploy checks. |
| `make run` | Starts the local Django development server. |
| `make worker` | Starts the Celery asynchronous worker process. |
| `make seed` | Populates demo data across all business domains. |
| `make deps-check` | Audits dependency locks and runs `pip-audit` for known vulnerabilities. |

---

## 🔒 Hard Architecture Invariants

1. **Service Layer Pattern**: All mutating business logic lives exclusively in `apps/<app>/services.py` wrapped in `@transaction.atomic`. Views and DRF viewsets only parse input and delegate to services.
2. **Read/Write Separation**: All read and reporting queries reside in `apps/<app>/selectors.py` using explicit `select_related` and `prefetch_related` to eliminate N+1 queries.
3. **Multi-Tenant Isolation**: Every business model inherits from `TenantModel`, indexes begin with `organization_id`, and PostgreSQL Row-Level Security (RLS) is strictly enforced at the database layer.
4. **General Ledger Immutability**: Posted financial and stock records are append-only. Adjustments and cancellations are executed strictly through symmetrical reversing entries.
5. **Transactional Outbox Events**: State-changing operations publish domain events through the transactional outbox table in the same database transaction, ensuring zero loss of downstream events.
6. **3-Layer Permission Gate**: Every HTTP endpoint enforces: 1) Subscription plan entitlement; 2) User role permission; 3) Object-level tenant scoping.

---

## 📚 Documentation & Guides

- **[REST API Guide](docs/API_GUIDE.md)**: Full API documentation with `curl` and `Python` examples for all domain resources.
- **[Integration Guide](docs/INTEGRATION_GUIDE.md)**: Webhook HMAC verification, API key rotation, OAuth 2.0 PKCE, and connector framework.
- **[Production Packaging & Operations](docs/05-production-packaging.md)**: Docker container topology, backup/restore runbooks, and disaster recovery.
- **[Architecture Deep-Dive](docs/01-architecture.md)**: Domain layout, boundary contracts, and modular monolith design.
- **[Design System](docs/design/design-system.md)**: Calm Ledger design principles, color palettes, and component library.
- **[Interactive Swagger Docs](http://localhost:8000/api/docs/)**: Live Swagger UI for interactive API exploration.
- **In-App Help Center**: Searchable user documentation built directly into the application at `/help/`.

---

## 📄 License
This project is licensed under the MIT License.