"""Initial schema – matches existing tables.

Revision ID: 0001
Revises: None
Create Date: 2026-03-02

This migration is a baseline: it creates the tables only if they do
not already exist, so it is safe to run on a database that was
bootstrapped by the old init_db() code.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
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
    """)

    op.execute("""
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
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id BIGSERIAL PRIMARY KEY,
        watch_id BIGINT NOT NULL REFERENCES price_watches(id),
        price DOUBLE PRECISION NOT NULL,
        captured_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id BIGSERIAL PRIMARY KEY,
        alert_type TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        payload_json TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        read BOOLEAN DEFAULT FALSE
    );
    """)

    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_items_type_created
    ON items(item_type, created_at DESC);
    """)

    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_alerts_read_created
    ON alerts(read, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS price_history;")
    op.execute("DROP TABLE IF EXISTS price_watches;")
    op.execute("DROP TABLE IF EXISTS alerts;")
    op.execute("DROP TABLE IF EXISTS items;")
