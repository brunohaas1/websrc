#!/usr/bin/env sh
# ── Scheduled PostgreSQL backup ──────────────────────────
# Usage: ./infra/pg_backup.sh  (or via cron / Docker sidecar)
# Env vars: PGHOST, PGUSER, PGDATABASE, PGPASSWORD, BACKUP_DIR, BACKUP_RETAIN_DAYS
set -e

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-7}"
PGHOST="${PGHOST:-postgres}"
PGUSER="${PGUSER:-dashboard}"
PGDATABASE="${PGDATABASE:-dashboard}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
FILENAME="${PGDATABASE}_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[pg_backup] Starting backup: ${FILENAME}"
pg_dump -h "$PGHOST" -U "$PGUSER" -d "$PGDATABASE" --no-owner --no-acl | gzip > "${BACKUP_DIR}/${FILENAME}"

SIZE=$(du -sh "${BACKUP_DIR}/${FILENAME}" | cut -f1)
echo "[pg_backup] Saved ${BACKUP_DIR}/${FILENAME} (${SIZE})"

# Prune old backups
if [ "$RETAIN_DAYS" -gt 0 ]; then
  PRUNED=$(find "$BACKUP_DIR" -name "${PGDATABASE}_*.sql.gz" -mtime +"$RETAIN_DAYS" -print -delete | wc -l)
  echo "[pg_backup] Pruned ${PRUNED} backups older than ${RETAIN_DAYS} days"
fi

echo "[pg_backup] Done."
