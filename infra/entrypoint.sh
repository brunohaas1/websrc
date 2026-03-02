#!/usr/bin/env sh
# ── Docker entrypoint: run Alembic migrations then exec CMD ──
set -e

# Only run Alembic when DATABASE_URL points to PostgreSQL
if echo "${DATABASE_URL:-}" | grep -qi "^postgresql"; then
  echo "[entrypoint] Running Alembic migrations..."
  python -m alembic upgrade head 2>&1 || echo "[entrypoint] WARNING: Alembic migration failed, falling back to init_db"
  echo "[entrypoint] Migrations complete."
fi

exec "$@"
