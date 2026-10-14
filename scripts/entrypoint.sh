#!/usr/bin/env bash
set -eo pipefail

echo "==> Business OS Container Entrypoint"

# Wait for PostgreSQL if database host or URL is configured
if [ -n "$DATABASE_URL" ] || [ -n "$POSTGRES_HOST" ]; then
    echo "==> Verifying database availability..."
    python manage.py wait_for_db --timeout=60 || true
fi

# Run database migrations if configured
if [ "$RUN_MIGRATIONS" = "true" ] || [ "$RUN_MIGRATIONS" = "1" ]; then
    echo "==> Running database migrations..."
    python manage.py migrate --noinput
fi

# Seed demo data if requested
if [ "$SEED_DEMO" = "true" ] || [ "$SEED_DEMO" = "1" ]; then
    echo "==> Seeding initial demo datasets..."
    python manage.py seed_demo --noinput || true
fi

echo "==> Starting process: $@"
exec "$@"
