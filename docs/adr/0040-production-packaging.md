# ADR 0040: Production Packaging: Multi-Stage Dockerfile, Docker Compose Orchestration, Reverse Proxy, and Disaster Recovery

## Context
Deploying Business OS as an enterprise multi-tenant ERP requires a production-grade infrastructure package. The system requires concurrent WSGI serving, scalable Celery workers for async tasks, periodic task dispatching via Celery Beat, persistent PostgreSQL 18 with Row-Level Security, Redis 8 for caching and queuing, automated TLS with HTTP/3 and asset compression, unprivileged container execution, and audited disaster recovery tooling.

## Decision
1. **Multi-Stage Production Dockerfile**:
   - `builder` stage: Uses Python 3.14 + `uv` to resolve and install frozen dependencies (`--no-dev`), pre-compile Tailwind CSS standalone bundles, and collect WhiteNoise static assets.
   - `runtime` stage: Minimal `python:3.14-slim-bookworm` container running as non-root `appuser` (UID 10001). Exposes port 8000 with a native Docker `HEALTHCHECK` probing `/healthz`.
   - Entrypoint: `scripts/entrypoint.sh` executing `wait_for_db` with exponential backoff and conditional zero-downtime migration execution (`RUN_MIGRATIONS=true`).
   - Gunicorn: Configured with 4 threaded workers (`gthread`, 4 threads/worker) and structured access/error logging to stdout.

2. **Docker Compose Production Topology (`docker-compose.prod.yml`)**:
   - `web`: Gunicorn WSGI web service exposed on internal network with healthcheck.
   - `worker`: Celery worker consuming `default`, `high`, `low` queues with 4 concurrency threads.
   - `beat`: Celery beat dispatcher triggering periodic transactional outbox flushing and schedules.
   - `db`: PostgreSQL 18 with persistent volume (`db_data`) and `pg_isready` healthcheck.
   - `redis`: Redis 8 with persistent append-only storage (`redis_data`) and ping healthcheck.
   - `caddy`: Reverse proxy handling TLS certificates (Let's Encrypt), HTTP/3 (QUIC), zstd/gzip compression, and immutable static asset disk serving.
   - Network isolation: Internal network for DB/Redis/Worker/Beat; public bridge network for Caddy proxy.

3. **Reverse Proxy Architecture**:
   - Primary: Caddy 2 (`Caddyfile`) with automatic Let's Encrypt TLS and immutable static asset caching (`Cache-Control: public, max-age=31536000, immutable`).
   - Alternative: Enterprise Nginx configuration (`nginx/nginx.conf`) with JSON access logging and upstream keepalive pooling.

4. **Disaster Recovery & Operational Tooling**:
   - `scripts/backup.sh` & `scripts/backup.py`: Performs non-blocking `pg_dump` with gzip compression, generates timestamped archives (`bos_backup_YYYYMMDD_HHMMSS.sql.gz`), and computes SHA256 checksums (`.sha256`).
   - `scripts/restore.sh` & `scripts/restore.py`: Verifies cryptographic SHA256 integrity prior to execution, streams decompressed dump to PostgreSQL, and validates schema table counts post-restore.
   - Management command: `python manage.py wait_for_db` for container readiness synchronization.
   - Environment documentation: `.env.example` and `docs/05-production-packaging.md`.

## Consequences
- Single-command production deployment (`docker compose -f docker-compose.prod.yml up -d`).
- Zero-drift container reproducibility across cloud providers and bare-metal servers.
- Cryptographically validated backup and restore runbooks protect against data corruption.
- Principle of least privilege enforced via non-root container user and internal network isolation.
