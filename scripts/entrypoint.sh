#!/usr/bin/env bash
set -eo pipefail

echo "==> Business OS Container Entrypoint"

PORT="${PORT:-8000}"

# Wait for PostgreSQL if database host or URL is configured
if [ -n "$DATABASE_URL" ] || [ -n "$POSTGRES_HOST" ]; then
    echo "==> Verifying database availability..."
    python manage.py wait_for_db --timeout=60 || true
fi

# Run database migrations by default if database is configured (or when RUN_MIGRATIONS is set)
if [ "${RUN_MIGRATIONS:-true}" = "true" ] || [ "$RUN_MIGRATIONS" = "1" ]; then
    echo "==> Running database migrations..."
    python manage.py migrate --noinput
fi

# Seed demo data if requested
if [ "$SEED_DEMO" = "true" ] || [ "$SEED_DEMO" = "1" ]; then
    echo "==> Seeding initial demo datasets..."
    python manage.py seed_demo --noinput || true
fi

# Optional: start embedded Celery worker if configured
if [ "${START_CELERY_WORKER:-false}" = "true" ] || [ "${ENABLE_CELERY_WORKER:-false}" = "true" ]; then
    echo "==> Starting embedded background Celery worker..."
    celery -A config worker --loglevel=info -P solo &
    CELERY_PID=$!
    trap "kill -TERM $CELERY_PID 2>/dev/null || true" EXIT
fi

# If command starts with gunicorn, ensure it binds to dynamic $PORT and respects $WEB_CONCURRENCY
if [ "$1" = "gunicorn" ]; then
    WORKERS="${WEB_CONCURRENCY:-2}"
    NEW_ARGS=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            0.0.0.0:8000)
                NEW_ARGS+=("0.0.0.0:${PORT}")
                shift
                ;;
            --workers)
                NEW_ARGS+=("--workers" "$WORKERS")
                shift 2
                ;;
            *)
                NEW_ARGS+=("$1")
                shift
                ;;
        esac
    done
    set -- "${NEW_ARGS[@]}"
fi

echo "==> Starting process: $@"
exec "$@"
