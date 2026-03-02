import sqlite3
from contextlib import contextmanager
from pathlib import Path

try:
    import psycopg  # type: ignore[import-not-found]
    from psycopg.rows import dict_row  # type: ignore[import-not-found]
    from psycopg_pool import ConnectionPool  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional at import time
    psycopg = None
    dict_row = None
    ConnectionPool = None  # type: ignore[assignment,misc]

_pg_pool = None


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    summary TEXT,
    image_url TEXT,
    published_at TEXT,
    extra_json TEXT,
    dedup_key TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    product_url TEXT NOT NULL,
    css_selector TEXT,
    target_price REAL NOT NULL,
    last_price REAL,
    currency TEXT DEFAULT 'BRL',
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL,
    price REAL NOT NULL,
    captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (watch_id) REFERENCES price_watches(id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    read INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_items_type_created
ON items(item_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_read_created
ON alerts(read, created_at DESC);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id BIGSERIAL PRIMARY KEY,
    item_type TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    summary TEXT,
    image_url TEXT,
    published_at TEXT,
    extra_json TEXT,
    dedup_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_watches (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    product_url TEXT NOT NULL,
    css_selector TEXT,
    target_price DOUBLE PRECISION NOT NULL,
    last_price DOUBLE PRECISION,
    currency TEXT DEFAULT 'BRL',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_history (
    id BIGSERIAL PRIMARY KEY,
    watch_id BIGINT NOT NULL REFERENCES price_watches(id),
    price DOUBLE PRECISION NOT NULL,
    captured_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    read BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_items_type_created
ON items(item_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_read_created
ON alerts(read, created_at DESC);
"""


def is_postgres_target(database_target: str) -> bool:
    target = str(database_target or "").lower()
    return (
        target.startswith("postgresql://")
        or target.startswith("postgresql+")
        or target.startswith("postgres://")
    )


def _postgres_dsn(database_target: str) -> str:
    dsn = str(database_target or "")
    if dsn.startswith("postgresql+"):
        scheme, rest = dsn.split("://", 1)
        base_scheme = scheme.split("+", 1)[0]
        return f"{base_scheme}://{rest}"
    return dsn


def init_db(database_target: str) -> None:
    if is_postgres_target(database_target):
        if psycopg is None:
            raise RuntimeError(
                "psycopg não instalado para DATABASE_URL PostgreSQL",
            )
        with psycopg.connect(_postgres_dsn(database_target)) as conn:
            with conn.cursor() as cursor:
                cursor.execute(POSTGRES_SCHEMA)
            conn.commit()

        global _pg_pool
        if ConnectionPool is not None and _pg_pool is None:
            _pg_pool = ConnectionPool(
                _postgres_dsn(database_target),
                min_size=2,
                max_size=10,
                kwargs={"row_factory": dict_row},
            )
        return

    db_path = Path(database_target)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_target) as conn:
        conn.executescript(SQLITE_SCHEMA)
        conn.commit()


@contextmanager
def get_connection(database_target: str):
    if is_postgres_target(database_target):
        if _pg_pool is not None:
            with _pg_pool.connection() as conn:
                yield conn
            return

        if psycopg is None or dict_row is None:
            raise RuntimeError(
                "psycopg não instalado para DATABASE_URL PostgreSQL",
            )
        conn = psycopg.connect(
            _postgres_dsn(database_target),
            row_factory=dict_row,
        )
        try:
            yield conn
        finally:
            conn.close()
        return

    conn = sqlite3.connect(database_target)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
