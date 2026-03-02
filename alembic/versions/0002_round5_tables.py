"""Round 5 – webhooks, shared_dashboards, notifications, price_watches.tags

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS webhooks (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        event_types TEXT DEFAULT '["alert"]',
        secret TEXT,
        active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS shared_dashboards (
        id BIGSERIAL PRIMARY KEY,
        token TEXT NOT NULL UNIQUE,
        label TEXT,
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id BIGSERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        notif_type TEXT DEFAULT 'info',
        read BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read, created_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_shared_dashboards_token ON shared_dashboards(token);")

    # Add tags column to price_watches (for feature #15)
    op.execute("""
    DO $$ BEGIN
        ALTER TABLE price_watches ADD COLUMN tags TEXT DEFAULT '[]';
    EXCEPTION WHEN duplicate_column THEN NULL;
    END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications;")
    op.execute("DROP TABLE IF EXISTS shared_dashboards;")
    op.execute("DROP TABLE IF EXISTS webhooks;")
    op.execute("ALTER TABLE price_watches DROP COLUMN IF EXISTS tags;")
