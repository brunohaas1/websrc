#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  PostgreSQL daily backup for websrc dashboard
#  Add to crontab: 0 3 * * * /path/to/backup-postgres.sh
# ─────────────────────────────────────────────────────────
set -euo pipefail

CONTAINER="${PG_CONTAINER:-ws-postgres}"
DB_NAME="${PG_DB:-dashboard}"
DB_USER="${PG_USER:-dashboard}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/websrc}"
KEEP_DAYS="${KEEP_DAYS:-7}"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz"

echo "[backup] Starting pg_dump of '$DB_NAME' from container '$CONTAINER'..."
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
  | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[backup] Saved: $BACKUP_FILE ($SIZE)"

# Prune old backups
DELETED=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +"$KEEP_DAYS" -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
  echo "[backup] Pruned $DELETED backup(s) older than $KEEP_DAYS days"
fi

echo "[backup] Done."
