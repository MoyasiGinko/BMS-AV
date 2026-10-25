# ADR 0044: Automated Railway Deployment Pipeline

## Context
Deploying Business OS on Railway (PaaS) requires zero-friction automated provisioning of the PostgreSQL 18 database, Redis 8 cache and Celery broker, and the containerized Django 6.1 web software upon git push.

## Decision
1. Provide dual-layer deployment configuration: `railway.json`, `railway.toml`, and `Procfile` (`release:` phase for database migrations, `web:` for Gunicorn with dynamic `$PORT` binding, and `worker:` for Celery).
2. Automate provisioning and configuration via `scripts/deploy_railway.sh` (Bash/Linux/CI) and `scripts/deploy_railway.ps1` (PowerShell/Windows). Scripts check/provision PostgreSQL and Redis plugins (`railway add -d postgres`, `railway add -d redis`), set reference variables (`${{Postgres.DATABASE_URL}}`, `${{Redis.REDIS_URL}}`), and generate a secure `SECRET_KEY`.
3. Provide `.github/workflows/railway-deploy.yml` to trigger automated builds and deployment on every git push using `RAILWAY_TOKEN`.
4. Update `scripts/entrypoint.sh` to dynamically adapt Gunicorn to `$PORT`, execute automated migrations (`RUN_MIGRATIONS=true`), and optionally supervise background Celery workers.
5. In `config/settings/prod.py`, automatically whitelist `.railway.app` and `RAILWAY_PUBLIC_DOMAIN` in `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.

## Consequences
- Every git push to a connected branch builds, provisions DB + Redis, migrates schema, and launches the application automatically.
- Zero manual host, port, or environment variable configuration needed for new Railway projects.
