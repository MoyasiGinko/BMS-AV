#!/usr/bin/env bash
# ==============================================================================
# Business OS: Automated Database Backup Script
# Creates a compressed, timestamped PostgreSQL database dump and SHA256 checksum
# ==============================================================================

set -eo pipefail

BACKUP_DIR="${1:-./backups}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILENAME="bos_backup_${TIMESTAMP}.sql.gz"
BACKUP_FILEpath="${BACKUP_DIR}/${BACKUP_FILENAME}"
CHECKSUM_FILE="${BACKUP_FILEpath}.sha256"

echo "==> [$(date +'%Y-%m-%d %H:%M:%S')] Starting Business OS database backup..."

# Extract connection parameters or use defaults
DB_NAME="${POSTGRES_DB:-bos}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"

if [ -n "$DATABASE_URL" ]; then
    echo "==> Executing pg_dump via DATABASE_URL..."
    pg_dump "$DATABASE_URL" --no-owner --no-privileges | gzip -9 > "$BACKUP_FILEpath"
else
    echo "==> Executing pg_dump on ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}..."
    PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --no-owner \
        --no-privileges | gzip -9 > "$BACKUP_FILEpath"
fi

if [ ! -s "$BACKUP_FILEpath" ]; then
    echo "ERROR: Backup file was created empty or missing!" >&2
    exit 1
fi

echo "==> Computing cryptographic SHA256 checksum..."
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$BACKUP_FILEpath" > "$CHECKSUM_FILE"
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$BACKUP_FILEpath" > "$CHECKSUM_FILE"
fi

BACKUP_SIZE=$(du -h "$BACKUP_FILEpath" | cut -f1)
echo "==> SUCCESS: Database backup created successfully!"
echo "    Archive:  ${BACKUP_FILEpath} (${BACKUP_SIZE})"
echo "    Checksum: ${CHECKSUM_FILE}"
