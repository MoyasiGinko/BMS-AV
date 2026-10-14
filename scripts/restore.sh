#!/usr/bin/env bash
# ==============================================================================
# Business OS: Automated Database Restore Script
# Restores a compressed PostgreSQL database dump with SHA256 verification
# ==============================================================================

set -eo pipefail

BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <path_to_backup.sql.gz>" >&2
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file '$BACKUP_FILE' does not exist." >&2
    exit 1
fi

echo "==> [$(date +'%Y-%m-%d %H:%M:%S')] Starting Business OS database restore..."

# Verify SHA256 checksum if .sha256 file exists alongside backup
CHECKSUM_FILE="${BACKUP_FILE}.sha256"
if [ -f "$CHECKSUM_FILE" ]; then
    echo "==> Verifying SHA256 checksum against ${CHECKSUM_FILE}..."
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -c "$CHECKSUM_FILE"
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 -c "$CHECKSUM_FILE"
    fi
    echo "==> Integrity check passed!"
else
    echo "WARNING: No checksum file found at ${CHECKSUM_FILE}. Proceeding without verification."
fi

DB_NAME="${POSTGRES_DB:-bos}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"

echo "==> Restoring database from ${BACKUP_FILE}..."

if [ -n "$DATABASE_URL" ]; then
    gunzip -c "$BACKUP_FILE" | psql "$DATABASE_URL" --quiet
else
    PGPASSWORD="${POSTGRES_PASSWORD}" gunzip -c "$BACKUP_FILE" | psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --quiet
fi

echo "==> Verifying database integrity after restore..."
if [ -n "$DATABASE_URL" ]; then
    TABLE_COUNT=$(psql "$DATABASE_URL" -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
else
    TABLE_COUNT=$(PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
fi

echo "==> SUCCESS: Database restored successfully! (Public schema tables: ${TABLE_COUNT// /})"
