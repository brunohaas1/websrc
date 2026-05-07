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


def close_pool() -> None:
    """Gracefully close the PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is not None:
        try:
            _pg_pool.close()
        except Exception:
            pass
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
    tags TEXT DEFAULT '[]',
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

CREATE TABLE IF NOT EXISTS custom_feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    feed_url TEXT NOT NULL UNIQUE,
    item_type TEXT DEFAULT 'news',
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    tags TEXT DEFAULT '[]',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS service_monitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    check_method TEXT DEFAULT 'GET',
    expected_status INTEGER DEFAULT 200,
    timeout_seconds INTEGER DEFAULT 5,
    active INTEGER DEFAULT 1,
    last_status TEXT DEFAULT 'unknown',
    last_latency_ms REAL,
    last_checked_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS service_monitor_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL,
    checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (monitor_id) REFERENCES service_monitors(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS currency_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    rate REAL NOT NULL,
    variation REAL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    highlights_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL UNIQUE,
    keys_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS saved_filters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    filter_json TEXT NOT NULL,
    is_favorite INTEGER DEFAULT 0,
    is_template INTEGER DEFAULT 0,
    description TEXT,
    last_used_at TEXT,
    use_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    event_types TEXT DEFAULT '["alert"]',
    secret TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shared_dashboards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    label TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    notif_type TEXT DEFAULT 'info',
    read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_items_type_created
ON items(item_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_read_created
ON alerts(read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_watch_id
ON price_history(watch_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_dedup_key
ON items(dedup_key);
CREATE INDEX IF NOT EXISTS idx_favorites_item_id
ON favorites(item_id);
CREATE INDEX IF NOT EXISTS idx_notes_item_id
ON notes(item_id);
CREATE INDEX IF NOT EXISTS idx_service_monitor_history_monitor_id
ON service_monitor_history(monitor_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_currency_rates_pair
ON currency_rates(pair, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_read
ON notifications(read, created_at DESC);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_shared_dashboards_token
ON shared_dashboards(token);

CREATE TABLE IF NOT EXISTS fin_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'stock',
    currency TEXT DEFAULT 'BRL',
    current_price REAL,
    previous_close REAL,
    day_change REAL,
    day_change_pct REAL,
    market_cap REAL,
    volume REAL,
    extra_json TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_assets_symbol
ON fin_assets(symbol);

CREATE TABLE IF NOT EXISTS fin_asset_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    price REAL NOT NULL,
    volume REAL,
    captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES fin_assets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fin_asset_history_asset
ON fin_asset_history(asset_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS fin_portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    quantity REAL NOT NULL DEFAULT 0,
    avg_price REAL NOT NULL DEFAULT 0,
    total_invested REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES fin_assets(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_portfolio_asset
ON fin_portfolio(asset_id);

CREATE TABLE IF NOT EXISTS fin_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    tx_type TEXT NOT NULL DEFAULT 'buy',
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    total REAL NOT NULL,
    fees REAL DEFAULT 0,
    notes TEXT,
    tx_date TEXT DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES fin_assets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fin_transactions_asset
ON fin_transactions(asset_id, tx_date DESC);

CREATE TABLE IF NOT EXISTS fin_watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'stock',
    target_price REAL,
    alert_above INTEGER DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_watchlist_symbol
ON fin_watchlist(symbol);

CREATE TABLE IF NOT EXISTS fin_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_amount REAL NOT NULL,
    current_amount REAL DEFAULT 0,
    deadline TEXT,
    category TEXT DEFAULT 'savings',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fin_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'bank',
    currency TEXT DEFAULT 'BRL',
    initial_balance REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_accounts_type
ON fin_accounts(account_type);

CREATE TABLE IF NOT EXISTS fin_debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creditor TEXT NOT NULL,
    description TEXT,
    principal REAL NOT NULL DEFAULT 0,
    current_balance REAL NOT NULL DEFAULT 0,
    interest_rate REAL NOT NULL DEFAULT 0,
    monthly_payment REAL NOT NULL DEFAULT 0,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    category TEXT DEFAULT 'personal',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_debts_status
ON fin_debts(status);

CREATE TABLE IF NOT EXISTS fin_cashflow_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT,
    subcategory TEXT,
    cost_center TEXT,
    account_id INTEGER REFERENCES fin_accounts(id) ON DELETE SET NULL,
    description TEXT,
    entry_date TEXT NOT NULL,
    notes TEXT,
    tags_json TEXT DEFAULT '[]',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    credit_card_id INTEGER REFERENCES fin_credit_cards(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_fin_cashflow_entry_date
ON fin_cashflow_entries(entry_date DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS fin_cashflow_recurring (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    active INTEGER NOT NULL DEFAULT 1,
    entry_type TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT,
    subcategory TEXT,
    cost_center TEXT,
    description TEXT,
    notes TEXT,
    tags_json TEXT DEFAULT '[]',
    frequency TEXT NOT NULL DEFAULT 'monthly',
    day_of_month INTEGER NOT NULL DEFAULT 1,
    start_date TEXT,
    end_date TEXT,
    last_generated_month TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_cashflow_recurring_active
ON fin_cashflow_recurring(active, frequency, day_of_month);

CREATE TABLE IF NOT EXISTS fin_cashflow_reconcile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    settled_at TEXT,
    reconciled_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entry_id) REFERENCES fin_cashflow_entries(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fin_cashflow_reconcile_status
ON fin_cashflow_reconcile(status, settled_at DESC);

CREATE TABLE IF NOT EXISTS fin_cashflow_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    mime_type TEXT,
    file_size INTEGER NOT NULL DEFAULT 0,
    file_blob BLOB NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entry_id) REFERENCES fin_cashflow_entries(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fin_cashflow_attachments_entry
ON fin_cashflow_attachments(entry_id, created_at DESC);

CREATE TABLE IF NOT EXISTS fin_dividends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    div_type TEXT NOT NULL DEFAULT 'dividend',
    amount_per_share REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL DEFAULT 0,
    quantity REAL NOT NULL DEFAULT 0,
    ex_date TEXT,
    pay_date TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES fin_assets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fin_dividends_asset
ON fin_dividends(asset_id, pay_date DESC);

CREATE TABLE IF NOT EXISTS fin_allocation_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT NOT NULL UNIQUE,
    target_pct REAL NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fin_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER,
    payload_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_audit_logs_created
ON fin_audit_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS fin_ocr_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_hash TEXT,
    merchant TEXT,
    cnpj TEXT,
    amount REAL,
    entry_date TEXT,
    category TEXT,
    entry_type TEXT,
    receipt_type TEXT,
    payment_method TEXT,
    confidence REAL,
    raw_text TEXT,
    payload_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_ocr_scans_created
ON fin_ocr_scans(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fin_ocr_scans_cnpj
ON fin_ocr_scans(cnpj, created_at DESC);

CREATE TABLE IF NOT EXISTS fin_credit_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    limit_amount REAL NOT NULL DEFAULT 0,
    closing_day INTEGER DEFAULT 1,
    due_day INTEGER DEFAULT 10,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
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
    tags TEXT DEFAULT '[]',
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

CREATE TABLE IF NOT EXISTS custom_feeds (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    feed_url TEXT NOT NULL UNIQUE,
    item_type TEXT DEFAULT 'news',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS favorites (
    id BIGSERIAL PRIMARY KEY,
    item_id BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tags TEXT DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
    id BIGSERIAL PRIMARY KEY,
    item_id BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS service_monitors (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    check_method TEXT DEFAULT 'GET',
    expected_status INTEGER DEFAULT 200,
    timeout_seconds INTEGER DEFAULT 5,
    active BOOLEAN DEFAULT TRUE,
    last_status TEXT DEFAULT 'unknown',
    last_latency_ms DOUBLE PRECISION,
    last_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS service_monitor_history (
    id BIGSERIAL PRIMARY KEY,
    monitor_id BIGINT NOT NULL REFERENCES service_monitors(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    latency_ms DOUBLE PRECISION,
    checked_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS currency_rates (
    id BIGSERIAL PRIMARY KEY,
    pair TEXT NOT NULL,
    rate DOUBLE PRECISION NOT NULL,
    variation DOUBLE PRECISION,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_digests (
    id BIGSERIAL PRIMARY KEY,
    digest_date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    highlights_json TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    endpoint TEXT NOT NULL UNIQUE,
    keys_json TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS saved_filters (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    filter_json TEXT NOT NULL,
    is_favorite BOOLEAN DEFAULT FALSE,
    is_template BOOLEAN DEFAULT FALSE,
    description TEXT,
    last_used_at TIMESTAMPTZ,
    use_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS webhooks (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    event_types TEXT DEFAULT '["alert"]',
    secret TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shared_dashboards (
    id BIGSERIAL PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,
    label TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    notif_type TEXT DEFAULT 'info',
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_items_type_created
ON items(item_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_read_created
ON alerts(read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_watch_id
ON price_history(watch_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_dedup_key
ON items(dedup_key);
CREATE INDEX IF NOT EXISTS idx_favorites_item_id
ON favorites(item_id);
CREATE INDEX IF NOT EXISTS idx_notes_item_id
ON notes(item_id);
CREATE INDEX IF NOT EXISTS idx_service_monitor_history_monitor_id
ON service_monitor_history(monitor_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_currency_rates_pair
ON currency_rates(pair, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_read
ON notifications(read, created_at DESC);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_shared_dashboards_token
ON shared_dashboards(token);

CREATE TABLE IF NOT EXISTS fin_assets (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'stock',
    currency TEXT DEFAULT 'BRL',
    current_price DOUBLE PRECISION,
    previous_close DOUBLE PRECISION,
    day_change DOUBLE PRECISION,
    day_change_pct DOUBLE PRECISION,
    market_cap DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    extra_json TEXT DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_assets_symbol
ON fin_assets(symbol);

CREATE TABLE IF NOT EXISTS fin_asset_history (
    id BIGSERIAL PRIMARY KEY,
    asset_id BIGINT NOT NULL REFERENCES fin_assets(id) ON DELETE CASCADE,
    price DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION,
    captured_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_asset_history_asset
ON fin_asset_history(asset_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS fin_portfolio (
    id BIGSERIAL PRIMARY KEY,
    asset_id BIGINT NOT NULL REFERENCES fin_assets(id) ON DELETE CASCADE,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_invested DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_portfolio_asset
ON fin_portfolio(asset_id);

CREATE TABLE IF NOT EXISTS fin_transactions (
    id BIGSERIAL PRIMARY KEY,
    asset_id BIGINT NOT NULL REFERENCES fin_assets(id) ON DELETE CASCADE,
    tx_type TEXT NOT NULL DEFAULT 'buy',
    quantity DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    total DOUBLE PRECISION NOT NULL,
    fees DOUBLE PRECISION DEFAULT 0,
    notes TEXT,
    tx_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_transactions_asset
ON fin_transactions(asset_id, tx_date DESC);

CREATE TABLE IF NOT EXISTS fin_watchlist (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'stock',
    target_price DOUBLE PRECISION,
    alert_above BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_watchlist_symbol
ON fin_watchlist(symbol);

CREATE TABLE IF NOT EXISTS fin_goals (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    target_amount DOUBLE PRECISION NOT NULL,
    current_amount DOUBLE PRECISION DEFAULT 0,
    deadline TEXT,
    category TEXT DEFAULT 'savings',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fin_accounts (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'bank',
    currency TEXT DEFAULT 'BRL',
    initial_balance DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_accounts_type
ON fin_accounts(account_type);

CREATE TABLE IF NOT EXISTS fin_debts (
    id BIGSERIAL PRIMARY KEY,
    creditor TEXT NOT NULL,
    description TEXT,
    principal DOUBLE PRECISION NOT NULL DEFAULT 0,
    current_balance DOUBLE PRECISION NOT NULL DEFAULT 0,
    interest_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    monthly_payment DOUBLE PRECISION NOT NULL DEFAULT 0,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    category TEXT DEFAULT 'personal',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_debts_status
ON fin_debts(status);

CREATE TABLE IF NOT EXISTS fin_cashflow_entries (
    id BIGSERIAL PRIMARY KEY,
    entry_type TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    category TEXT,
    subcategory TEXT,
    cost_center TEXT,
    account_id BIGINT REFERENCES fin_accounts(id) ON DELETE SET NULL,
    description TEXT,
    entry_date DATE NOT NULL,
    notes TEXT,
    tags_json TEXT DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    credit_card_id BIGINT REFERENCES fin_credit_cards(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_fin_cashflow_entry_date
ON fin_cashflow_entries(entry_date DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS fin_cashflow_recurring (
    id BIGSERIAL PRIMARY KEY,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    entry_type TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    category TEXT,
    subcategory TEXT,
    cost_center TEXT,
    description TEXT,
    notes TEXT,
    tags_json TEXT DEFAULT '[]',
    frequency TEXT NOT NULL DEFAULT 'monthly',
    day_of_month INTEGER NOT NULL DEFAULT 1,
    start_date DATE,
    end_date DATE,
    last_generated_month TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_cashflow_recurring_active
ON fin_cashflow_recurring(active, frequency, day_of_month);

CREATE TABLE IF NOT EXISTS fin_cashflow_reconcile (
    id BIGSERIAL PRIMARY KEY,
    entry_id BIGINT NOT NULL UNIQUE REFERENCES fin_cashflow_entries(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    settled_at DATE,
    reconciled_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_cashflow_reconcile_status
ON fin_cashflow_reconcile(status, settled_at DESC);

CREATE TABLE IF NOT EXISTS fin_cashflow_attachments (
    id BIGSERIAL PRIMARY KEY,
    entry_id BIGINT NOT NULL REFERENCES fin_cashflow_entries(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    mime_type TEXT,
    file_size BIGINT NOT NULL DEFAULT 0,
    file_blob BYTEA NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_cashflow_attachments_entry
ON fin_cashflow_attachments(entry_id, created_at DESC);

CREATE TABLE IF NOT EXISTS fin_dividends (
    id BIGSERIAL PRIMARY KEY,
    asset_id BIGINT NOT NULL REFERENCES fin_assets(id) ON DELETE CASCADE,
    div_type TEXT NOT NULL DEFAULT 'dividend',
    amount_per_share DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
    ex_date TEXT,
    pay_date TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_dividends_asset
ON fin_dividends(asset_id, pay_date DESC);

CREATE TABLE IF NOT EXISTS fin_allocation_targets (
    id BIGSERIAL PRIMARY KEY,
    asset_type TEXT NOT NULL UNIQUE,
    target_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fin_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id BIGINT,
    payload_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fin_audit_logs_created
ON fin_audit_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS fin_credit_cards (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    limit_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    closing_day INTEGER DEFAULT 1,
    due_day INTEGER DEFAULT 10,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
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
                # Incremental column migrations (idempotent via ADD COLUMN IF NOT EXISTS)
                for stmt in (
                    "ALTER TABLE fin_cashflow_entries ADD COLUMN IF NOT EXISTS installment_group TEXT",
                    "ALTER TABLE fin_cashflow_entries ADD COLUMN IF NOT EXISTS installment_index INTEGER",
                    "ALTER TABLE fin_cashflow_entries ADD COLUMN IF NOT EXISTS installment_total INTEGER",
                    "ALTER TABLE fin_cashflow_entries ADD COLUMN IF NOT EXISTS credit_card_id BIGINT REFERENCES fin_credit_cards(id) ON DELETE SET NULL",
                    "ALTER TABLE fin_cashflow_entries ADD COLUMN IF NOT EXISTS account_id BIGINT REFERENCES fin_accounts(id) ON DELETE SET NULL",
                ):
                    cursor.execute(stmt)
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_account ON fin_cashflow_entries(account_id)",
                )
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
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SQLITE_SCHEMA)
        _run_sqlite_migrations(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_account ON fin_cashflow_entries(account_id)",
        )
        conn.commit()


def _run_sqlite_migrations(conn: sqlite3.Connection) -> None:
    """Apply incremental column additions to existing SQLite tables (idempotent)."""
    _try_add_column(conn, "fin_cashflow_entries", "installment_group", "TEXT")
    _try_add_column(conn, "fin_cashflow_entries", "installment_index", "INTEGER")
    _try_add_column(conn, "fin_cashflow_entries", "installment_total", "INTEGER")
    _try_add_column(conn, "fin_cashflow_entries", "credit_card_id", "INTEGER")
    _try_add_column(conn, "fin_cashflow_entries", "account_id", "INTEGER")


def _try_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


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
