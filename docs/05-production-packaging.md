# Production Packaging & Operations Guide

This guide describes the production deployment topology, environment configuration, container orchestration, reverse proxy setup, and operational disaster recovery runbooks for Business OS.

---

## 1. Architecture Topology

```
                       [ Internet ]
                            |
                   (HTTPS :443 / :80)
                            |
             +------------------------------+
             |   Caddy / Nginx Proxy        |
             |  - Automatic Let's Encrypt   |
             |  - Static / Media Disk Cache |
             |  - Zstandard & Gzip Compress |
             +------------------------------+
                            |
                     (HTTP :8000)
                            |
             +------------------------------+
             |    Web App (Gunicorn WSGI)   |
             |  - Django 6.1 (4 threads/w)  |
             |  - WhiteNoise Static Core    |
             |  - Tenant Middleware & RLS   |
             +------------------------------+
                  |                    |
        (PostgreSQL :5432)       (Redis :6379)
                  |                    |
       +--------------------+  +--------------------+
       |  PostgreSQL 18 DB  |  |  Redis 8 Engine    |
       |  - RLS Policies    |  |  - DB 0: Cache     |
       |  - Persistent Vol  |  |  - DB 1: Celery Q  |
       |  - ACID Wal & Data |  |  - DB 2: Celery Res|
       +--------------------+  +--------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
      +-------------------------+             +-------------------------+
      | Celery Worker Container |             |  Celery Beat Container  |
      | - default, high, low Qs |             |  - Periodic Schedules   |
      | - 4 concurrent workers  |             |  - Outbox, Reminders    |
      +-------------------------+             +-------------------------+
```

---

## 2. Environment Variables Reference

| Variable | Type | Default | Required in Prod | Description |
|---|---|---|:---:|---|
| `SECRET_KEY` | String | `None` | **Yes** | Django cryptographic secret key (>= 50 chars). |
| `DEBUG` | Boolean | `False` | **Yes** | Must remain `False` in production. |
| `ALLOWED_HOSTS` | List[str] | `[]` | **Yes** | Comma-separated list of hostnames/domains. |
| `CSRF_TRUSTED_ORIGINS` | List[str] | `[]` | **Yes** | Trusted origins for CSRF POST requests (`https://...`). |
| `DATABASE_URL` | URL | `None` | **Yes** | PostgreSQL connection URL: `postgres://user:pass@host:5432/db`. |
| `REDIS_URL` | URL | `redis://localhost:6379/0` | **Yes** | Redis URL for application cache. |
| `CELERY_BROKER_URL` | URL | `redis://localhost:6379/1` | **Yes** | Redis URL for Celery message queues. |
| `CELERY_RESULT_BACKEND`| URL | `redis://localhost:6379/2` | **Yes** | Redis URL for Celery task results. |
| `FIELD_ENCRYPTION_KEY` | String | `None` | **Yes** | 32-byte URL-safe base64 key for encrypting sensitive fields. |
| `DOMAIN` | String | `localhost` | **Yes** | Primary domain name for Caddy automatic TLS. |
| `SECURE_SSL_REDIRECT` | Boolean | `True` | No | Automatically redirect HTTP to HTTPS. |
| `SECURE_HSTS_SECONDS` | Integer | `31536000` | No | HTTP Strict Transport Security duration (1 year). |
| `DEFAULT_FROM_EMAIL` | String | `no-reply@localhost` | No | Default `From:` email for notifications. |
| `EMAIL_HOST` | String | `localhost` | No | SMTP server hostname. |
| `EMAIL_PORT` | Integer | `587` | No | SMTP port (587 for TLS, 465 for SSL). |
| `EMAIL_HOST_USER` | String | `""` | No | SMTP username. |
| `EMAIL_HOST_PASSWORD` | String | `""` | No | SMTP password. |
| `EMAIL_USE_TLS` | Boolean | `True` | No | Enable STARTTLS. |
| `LOG_FORMAT` | String | `json` | No | `json` for structured JSON logs, `verbose` for local dev. |
| `LOG_LEVEL` | String | `INFO` | No | Minimum logging severity level. |
| `SENTRY_DSN` | String | `""` | No | Sentry error tracking DSN (optional). |
| `AI_PROVIDER` | String | `fake` | No | Active AI assistant provider (`fake`, `anthropic`, `openai`, `gemini`). |

---

## 3. Quickstart Deployment Guide

### Step 1: Clone and Configure Environment
```bash
git clone https://github.com/MoyasiGinko/BMS-AV.git /opt/business-os
cd /opt/business-os
cp .env.example .env.prod
nano .env.prod  # Populate SECRET_KEY, FIELD_ENCRYPTION_KEY, POSTGRES_PASSWORD, DOMAIN
```

### Step 2: Build and Launch Orchestration
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### Step 3: Verify Service Health
```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f web
curl -f http://localhost:8000/healthz
```

---

## 4. Reverse Proxy Options

### Option A: Caddy (Default, Recommended)
Caddy provides zero-configuration automated TLS certificate provisioning through Let's Encrypt, HTTP/3 (QUIC) support, and modern compression out of the box.
Configuration file: `Caddyfile`.

### Option B: Nginx
For enterprise infrastructures with custom edge reverse proxies or corporate load balancers:
Configuration file: `nginx/nginx.conf`.

---

## 5. Health & Readiness Monitoring

- **Liveness Probe**: `GET /healthz`
  Returns HTTP 200 `{"status": "ok", "uptime_seconds": ...}` when the WSGI process is alive.
- **Readiness Probe**: `GET /readyz`
  Verifies that PostgreSQL database connectivity, Redis cache connectivity, and Celery worker queues are operational.
