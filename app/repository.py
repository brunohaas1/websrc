from __future__ import annotations

import sqlite3
import calendar
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse

from .db import get_connection, is_postgres_target
from .utils import json_dumps, json_loads, to_dedup_key

try:
    from psycopg import errors as psycopg_errors  # pyright: ignore
except Exception:  # pragma: no cover - optional import
    psycopg_errors = None


class Repository:
    SEMANTIC_STOPWORDS = {
        "a",
        "as",
        "o",
        "os",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "um",
        "uma",
        "the",
        "and",
        "of",
        "to",
        "for",
        "in",
        "on",
        "with",
    }

    PREFERRED_AI_CATEGORIES = {
        "ia",
        "programacao",
        "seguranca",
        "open_source",
    }

    def __init__(self, database_target: str):
        self.database_target = database_target
        self.is_postgres = is_postgres_target(database_target)
        self._ensure_fin_cashflow_schema_evolution()

    def _ensure_fin_cashflow_schema_evolution(self) -> None:
        statements: list[str] = []
        if self.is_postgres:
            statements = [
                "ALTER TABLE fin_cashflow_entries ADD COLUMN IF NOT EXISTS subcategory TEXT",
                "ALTER TABLE fin_cashflow_entries ADD COLUMN IF NOT EXISTS cost_center TEXT",
                "ALTER TABLE fin_cashflow_entries ADD COLUMN IF NOT EXISTS tags_json TEXT DEFAULT '[]'",
                """
                CREATE TABLE IF NOT EXISTS fin_cashflow_reconcile (
                    entry_id BIGINT PRIMARY KEY REFERENCES fin_cashflow_entries(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    settled_at DATE,
                    reconciled_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "ALTER TABLE fin_cashflow_reconcile ADD COLUMN IF NOT EXISTS settled_at DATE",
                "ALTER TABLE fin_cashflow_reconcile ADD COLUMN IF NOT EXISTS reconciled_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_entry_type_date ON fin_cashflow_entries(entry_type, entry_date DESC)",
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_category_date ON fin_cashflow_entries(category, entry_date DESC)",
                """
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
                    day_rule TEXT NOT NULL DEFAULT 'exact',
                    start_date DATE,
                    end_date DATE,
                    last_generated_month TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "ALTER TABLE fin_cashflow_recurring ADD COLUMN IF NOT EXISTS day_rule TEXT NOT NULL DEFAULT 'exact'",
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_recurring_active ON fin_cashflow_recurring(active, frequency, day_of_month)",
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_reconcile_status ON fin_cashflow_reconcile(status, settled_at DESC)",
                """
                CREATE TABLE IF NOT EXISTS fin_cashflow_attachments (
                    id BIGSERIAL PRIMARY KEY,
                    entry_id BIGINT NOT NULL REFERENCES fin_cashflow_entries(id) ON DELETE CASCADE,
                    file_name TEXT NOT NULL,
                    mime_type TEXT,
                    file_size BIGINT NOT NULL DEFAULT 0,
                    file_blob BYTEA NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_attachments_entry ON fin_cashflow_attachments(entry_id, created_at DESC)",
            ]
        else:
            statements = [
                "ALTER TABLE fin_cashflow_entries ADD COLUMN subcategory TEXT",
                "ALTER TABLE fin_cashflow_entries ADD COLUMN cost_center TEXT",
                "ALTER TABLE fin_cashflow_entries ADD COLUMN tags_json TEXT DEFAULT '[]'",
                """
                CREATE TABLE IF NOT EXISTS fin_cashflow_reconcile (
                    entry_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL,
                    settled_at TEXT,
                    reconciled_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entry_id) REFERENCES fin_cashflow_entries(id) ON DELETE CASCADE
                )
                """,
                "ALTER TABLE fin_cashflow_reconcile ADD COLUMN settled_at TEXT",
                "ALTER TABLE fin_cashflow_reconcile ADD COLUMN reconciled_at TEXT DEFAULT CURRENT_TIMESTAMP",
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_entry_type_date ON fin_cashflow_entries(entry_type, entry_date DESC)",
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_category_date ON fin_cashflow_entries(category, entry_date DESC)",
                """
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
                    day_rule TEXT NOT NULL DEFAULT 'exact',
                    start_date TEXT,
                    end_date TEXT,
                    last_generated_month TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "ALTER TABLE fin_cashflow_recurring ADD COLUMN day_rule TEXT NOT NULL DEFAULT 'exact'",
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_recurring_active ON fin_cashflow_recurring(active, frequency, day_of_month)",
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_reconcile_status ON fin_cashflow_reconcile(status, settled_at DESC)",
                """
                CREATE TABLE IF NOT EXISTS fin_cashflow_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    mime_type TEXT,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    file_blob BLOB NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entry_id) REFERENCES fin_cashflow_entries(id) ON DELETE CASCADE
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_fin_cashflow_attachments_entry ON fin_cashflow_attachments(entry_id, created_at DESC)",
            ]

        with get_connection(self.database_target) as conn:
            for stmt in statements:
                try:
                    conn.execute(stmt)
                except Exception:
                    # SQLite raises duplicate-column errors on repeated ALTER TABLE.
                    pass
            conn.commit()

    def _sql(self, query: str) -> str:
        if not self.is_postgres:
            return query
        return query.replace("?", "%s")

    def _is_unique_violation(self, exc: Exception) -> bool:
        if isinstance(exc, sqlite3.IntegrityError):
            return True

        if psycopg_errors is not None and isinstance(
            exc,
            psycopg_errors.UniqueViolation,
        ):
            return True

        return "unique" in str(exc).lower()

    def upsert_item(self, item: dict[str, Any]) -> bool:
        dedup_key = to_dedup_key(
            item_type=item["item_type"],
            source=item["source"],
            url=item["url"],
            title=item["title"],
        )
        with get_connection(self.database_target) as conn:
            try:
                conn.execute(
                    self._sql(
                        """
                    INSERT INTO items (
                        item_type,
                        source,
                        title,
                        url,
                        summary,
                        image_url,
                        published_at,
                        extra_json,
                        dedup_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ),
                    (
                        item["item_type"],
                        item["source"],
                        item["title"],
                        item["url"],
                        item.get("summary"),
                        item.get("image_url"),
                        item.get("published_at"),
                        json_dumps(item.get("extra", {})),
                        dedup_key,
                    ),
                )
                conn.commit()
                return True
            except Exception as exc:
                if self._is_unique_violation(exc):
                    conn.rollback()
                    return False
                raise

    def item_exists(self, item: dict[str, Any]) -> bool:
        dedup_key = to_dedup_key(
            item_type=item["item_type"],
            source=item["source"],
            url=item["url"],
            title=item["title"],
        )
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql("SELECT 1 FROM items WHERE dedup_key = ? LIMIT 1"),
                (dedup_key,),
            ).fetchone()
            return row is not None

    def list_items(
        self,
        item_type: str | None = None,
        limit: int = 50,
        q: str | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM items WHERE 1=1"
        params: list[Any] = []

        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)

        if q:
            safe_q = (
                q.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            query += " AND (title LIKE ? OR summary LIKE ?)"
            params.extend([f"%{safe_q}%", f"%{safe_q}%"])

        if self.is_postgres:
            query += (
                " ORDER BY COALESCE("
                "NULLIF(published_at, ''), "
                "to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SSOF')"
                ") DESC"
            )
        else:
            query += (
                " ORDER BY COALESCE(published_at, created_at) DESC"
            )

        over_fetch_limit = max(limit * 5, 80)
        if offset > 0:
            query += " OFFSET ?"
            params.append(offset)
        query += " LIMIT ?"
        params.append(over_fetch_limit)

        with get_connection(self.database_target) as conn:
            rows = conn.execute(self._sql(query), params).fetchall()
            items = [self._item_row_to_dict(row) for row in rows]
            deduped = self._dedupe_items(items, over_fetch_limit)
            ranked = self._rank_items(deduped, item_type=item_type, q=q)
            return ranked[:limit]

    def count_items(
        self,
        item_type: str | None = None,
        q: str | None = None,
    ) -> int:
        """Return total items matching filters (for pagination)."""
        query = "SELECT COUNT(*) AS cnt FROM items WHERE 1=1"
        params: list[Any] = []

        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)

        if q:
            safe_q = (
                q.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            query += " AND (title LIKE ? OR summary LIKE ?)"
            params.extend([f"%{safe_q}%", f"%{safe_q}%"])

        with get_connection(self.database_target) as conn:
            row = conn.execute(self._sql(query), params).fetchone()
            if isinstance(row, dict):
                return int(row.get("cnt") or 0)
            return int(row[0]) if row else 0

    def get_dashboard_snapshot(self) -> dict[str, Any]:
        promotions = self.list_items("promotion", 40)
        deduped_promotions = self._dedupe_promotions(promotions)[:15]

        return {
            "news": self.list_items("news", 15),
            "promotions": deduped_promotions,
            "prices": self.list_price_watches(),
            "weather": self.list_items("weather", 1),
            "tech_ai": self.list_items("tech_ai", 15),
            "videos": self.list_items("youtube", 20),
            "releases": self.list_items("release", 20),
            "jobs": self.list_items("job", 20),
            "alerts": self.list_alerts(20),
            "ai_observability": self.get_ai_observability(),
        }

    def get_ai_observability(self) -> dict[str, Any]:
        observed_types = ("news", "tech_ai", "youtube", "job", "release")
        if self.is_postgres:
            return self._ai_observability_pg(observed_types)
        return self._ai_observability_lite(observed_types)

    # ------------------------------------------------------------------
    # PostgreSQL path – push aggregation into SQL
    # ------------------------------------------------------------------
    def _ai_observability_pg(
        self,
        observed_types: tuple[str, ...],
    ) -> dict[str, Any]:
        ej = "(COALESCE(NULLIF(extra_json,''),'{}'))::jsonb"

        with get_connection(self.database_target) as conn:
            # 1. Summary totals + avg latency -------------------------
            row = conn.execute(
                f"""
                SELECT
                  COUNT(*) AS total,
                  COUNT(*) FILTER (
                    WHERE NULLIF(TRIM({ej}->>'ai_summary'), '') IS NOT NULL
                  ) AS enriched,
                  AVG(
                    CASE
                      WHEN {ej}->>'ai_latency_ms'
                           ~ '^[0-9]+\\.?[0-9]*$'
                           AND ({ej}->>'ai_latency_ms')::float > 0
                      THEN ({ej}->>'ai_latency_ms')::float
                    END
                  ) AS avg_latency
                FROM items
                WHERE item_type IN (%s,%s,%s,%s,%s)
                  AND created_at >= NOW() - INTERVAL '24 hours'
                """,
                observed_types,
            ).fetchone()

            total = int(row["total"] or 0)
            enriched = int(row["enriched"] or 0)
            avg_latency = row["avg_latency"]

            # 2. Fallback rate by hour --------------------------------
            hourly = conn.execute(
                f"""
                SELECT
                  to_char(date_trunc('hour', created_at),
                          'YYYY-MM-DD HH24:00') AS hour,
                  COUNT(*) AS total,
                  COUNT(*) FILTER (
                    WHERE LOWER(COALESCE(
                      NULLIF(TRIM({ej}->>'ai_reason'),''),
                      'sem-motivo')) LIKE 'fallback%%'
                  ) AS fallback
                FROM items
                WHERE item_type IN (%s,%s,%s,%s,%s)
                  AND created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY date_trunc('hour', created_at)
                ORDER BY date_trunc('hour', created_at) DESC
                LIMIT 12
                """,
                observed_types,
            ).fetchall()

            # 3. Source accuracy --------------------------------------
            sources = conn.execute(
                f"""
                SELECT
                  LOWER(COALESCE(NULLIF(TRIM(source),''),
                                 'desconhecida')) AS src,
                  COUNT(*) FILTER (
                    WHERE NULLIF(TRIM({ej}->>'ai_summary'), '') IS NOT NULL
                  ) AS enriched_items,
                  COUNT(*) FILTER (
                    WHERE COALESCE({ej}->>'ai_reason','') = 'local-ai'
                  ) AS model_success
                FROM items
                WHERE item_type IN (%s,%s,%s,%s,%s)
                  AND created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY LOWER(COALESCE(NULLIF(TRIM(source),''),
                                        'desconhecida'))
                ORDER BY enriched_items DESC
                LIMIT 10
                """,
                observed_types,
            ).fetchall()

            # 4. Reason breakdown -------------------------------------
            reasons = conn.execute(
                f"""
                SELECT
                  COALESCE(NULLIF(TRIM({ej}->>'ai_reason'),''),
                           'sem-motivo') AS reason,
                  COUNT(*) AS total
                FROM items
                WHERE item_type IN (%s,%s,%s,%s,%s)
                  AND created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY reason
                ORDER BY total DESC
                LIMIT 10
                """,
                observed_types,
            ).fetchall()

        # ---- format results ----------------------------------------
        fallback_rate_by_hour: list[dict[str, Any]] = []
        for r in hourly:
            t, fb = int(r["total"]), int(r["fallback"])
            rate = (fb / t * 100) if t else 0.0
            fallback_rate_by_hour.append(
                {
                    "hour": r["hour"],
                    "fallback_rate": round(rate, 1),
                    "fallback": fb,
                    "total": t,
                }
            )

        source_accuracy: list[dict[str, Any]] = []
        for r in sources:
            ei, ms = int(r["enriched_items"]), int(r["model_success"])
            sr = (ms / ei * 100) if ei else 0.0
            source_accuracy.append(
                {
                    "source": r["src"],
                    "model_success_rate": round(sr, 1),
                    "enriched_items": ei,
                }
            )

        reason_breakdown = [
            {"reason": r["reason"], "total": int(r["total"])}
            for r in reasons
        ]

        return {
            "window_hours": 24,
            "total_items": total,
            "enriched_items": enriched,
            "enriched_percent": (
                round((enriched / total) * 100, 1) if total else 0.0
            ),
            "avg_ai_latency_ms": (
                round(float(avg_latency), 1) if avg_latency else None
            ),
            "fallback_rate_by_hour": fallback_rate_by_hour,
            "source_accuracy": source_accuracy,
            "reason_breakdown": reason_breakdown,
        }

    # ------------------------------------------------------------------
    # SQLite fallback – process in Python
    # ------------------------------------------------------------------
    def _ai_observability_lite(
        self,
        observed_types: tuple[str, ...],
    ) -> dict[str, Any]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                """
                SELECT source, extra_json, created_at
                FROM items
                WHERE item_type IN (?, ?, ?, ?, ?)
                  AND datetime(created_at) >= datetime('now', '-24 hours')
                """,
                observed_types,
            ).fetchall()

        total = 0
        enriched = 0
        latencies: list[float] = []
        per_hour: dict[str, dict[str, int]] = {}
        per_source: dict[str, dict[str, int]] = {}
        per_reason: dict[str, int] = {}

        def _to_datetime(value: Any) -> datetime | None:
            if isinstance(value, datetime):
                return value
            if not value:
                return None
            text = str(value).strip()
            if not text:
                return None
            normalized = text.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return None
            return parsed

        for row in rows:
            total += 1
            extra = json_loads(row["extra_json"])
            if not isinstance(extra, dict):
                extra = {}

            ai_summary = str(extra.get("ai_summary") or "").strip()
            has_enrichment = bool(ai_summary)
            if has_enrichment:
                enriched += 1

            raw_latency = extra.get("ai_latency_ms")
            try:
                parsed_latency = float(str(raw_latency))
                if parsed_latency > 0:
                    latencies.append(parsed_latency)
            except (TypeError, ValueError):
                pass

            reason = str(extra.get("ai_reason") or "sem-motivo").strip()
            if not reason:
                reason = "sem-motivo"
            per_reason[reason] = per_reason.get(reason, 0) + 1

            created_at = _to_datetime(row["created_at"])
            if created_at is not None:
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                hour_key = created_at.strftime("%Y-%m-%d %H:00")
                bucket = per_hour.setdefault(
                    hour_key,
                    {"total": 0, "fallback": 0},
                )
                bucket["total"] += 1
                if reason.lower().startswith("fallback"):
                    bucket["fallback"] += 1

            source = str(row["source"] or "desconhecida").strip().lower()
            if not source:
                source = "desconhecida"
            source_bucket = per_source.setdefault(
                source,
                {"enriched_items": 0, "model_success": 0},
            )
            if has_enrichment:
                source_bucket["enriched_items"] += 1
            if reason == "local-ai":
                source_bucket["model_success"] += 1

        fallback_rate_by_hour: list[dict[str, Any]] = []
        for hour, values in sorted(per_hour.items(), reverse=True)[:12]:
            total_hour = int(values.get("total", 0))
            fallback_hour = int(values.get("fallback", 0))
            rate = (fallback_hour / total_hour * 100) if total_hour else 0.0
            fallback_rate_by_hour.append(
                {
                    "hour": hour,
                    "fallback_rate": round(rate, 1),
                    "fallback": fallback_hour,
                    "total": total_hour,
                }
            )

        source_accuracy: list[dict[str, Any]] = []
        sorted_sources = sorted(
            per_source.items(),
            key=lambda item: item[1].get("enriched_items", 0),
            reverse=True,
        )
        for source, values in sorted_sources[:10]:
            enriched_items = int(values.get("enriched_items", 0))
            model_success = int(values.get("model_success", 0))
            success_rate = (
                (model_success / enriched_items) * 100
                if enriched_items
                else 0.0
            )
            source_accuracy.append(
                {
                    "source": source,
                    "model_success_rate": round(success_rate, 1),
                    "enriched_items": enriched_items,
                }
            )

        reason_breakdown = [
            {"reason": reason, "total": total_count}
            for reason, total_count in sorted(
                per_reason.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:10]
        ]

        avg_latency_value = (
            (sum(latencies) / len(latencies))
            if latencies
            else None
        )

        return {
            "window_hours": 24,
            "total_items": total,
            "enriched_items": enriched,
            "enriched_percent": (
                round((enriched / total) * 100, 1)
                if total
                else 0.0
            ),
            "avg_ai_latency_ms": (
                round(float(avg_latency_value), 1)
                if isinstance(avg_latency_value, (int, float))
                else None
            ),
            "fallback_rate_by_hour": fallback_rate_by_hour[:12],
            "source_accuracy": source_accuracy[:10],
            "reason_breakdown": reason_breakdown[:10],
        }

    def add_price_watch(self, payload: dict[str, Any]) -> int:
        with get_connection(self.database_target) as conn:
            query = """
                INSERT INTO price_watches (
                    name,
                    product_url,
                    css_selector,
                    target_price,
                    currency,
                    active
                )
                VALUES (?, ?, ?, ?, ?, 1)
            """
            if self.is_postgres:
                query += " RETURNING id"

            cursor = conn.execute(
                self._sql(query),
                (
                    payload["name"],
                    payload["product_url"],
                    payload.get("css_selector"),
                    payload["target_price"],
                    payload.get("currency", "BRL"),
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                inserted_id = row["id"] if row else 0
            else:
                inserted_id = (
                    cursor.lastrowid
                    if hasattr(cursor, "lastrowid")
                    else 0
                )
            return int(inserted_id or 0)

    def list_price_watches(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql(
                    """
                SELECT * FROM price_watches
                ORDER BY updated_at DESC
                """,
                ),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_price(self, watch_id: int, price: float) -> None:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql(
                    (
                        "INSERT INTO price_history "
                        "(watch_id, price) VALUES (?, ?)"
                    ),
                ),
                (watch_id, price),
            )
            conn.execute(
                self._sql(
                    """
                UPDATE price_watches
                SET last_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                ),
                (price, watch_id),
            )
            conn.commit()

    def get_price_history(
        self,
        watch_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql(
                    """
                SELECT watch_id, price, captured_at
                FROM price_history
                WHERE watch_id = ?
                ORDER BY captured_at DESC
                LIMIT ?
                """,
                ),
                (watch_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_alert(
        self,
        alert_type: str,
        title: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql(
                    """
                INSERT INTO alerts (alert_type, title, message, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                ),
                (alert_type, title, message, json_dumps(payload or {})),
            )
            conn.commit()

    def list_alerts(self, limit: int = 30) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql(
                    "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?",
                ),
                (limit,),
            ).fetchall()
            data = []
            for row in rows:
                payload = json_loads(row["payload_json"])
                item = dict(row)
                item["payload"] = payload
                data.append(item)
            return data

    def list_pending_ai_items(self, limit: int = 200) -> list[dict[str, Any]]:
        eligible_types = ("news", "tech_ai", "youtube", "job", "release")

        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                query = """
                SELECT *
                FROM items
                WHERE item_type IN (%s, %s, %s, %s, %s)
                  AND (
                      extra_json IS NULL
                      OR trim(extra_json) = ''
                      OR extra_json !~ '^\\s*\\{'
                      OR (extra_json::jsonb ->> 'ai_summary') IS NULL
                      OR trim(extra_json::jsonb ->> 'ai_summary') = ''
                      OR (extra_json::jsonb ->> 'ai_category') IS NULL
                      OR trim(extra_json::jsonb ->> 'ai_category') = ''
                  )
                ORDER BY created_at DESC
                LIMIT %s
                """
            else:
                query = """
                SELECT *
                FROM items
                WHERE item_type IN (?, ?, ?, ?, ?)
                  AND (
                      extra_json IS NULL
                      OR trim(extra_json) = ''
                      OR json_extract(extra_json, '$.ai_summary') IS NULL
                      OR trim(json_extract(extra_json, '$.ai_summary')) = ''
                      OR json_extract(extra_json, '$.ai_category') IS NULL
                      OR trim(json_extract(extra_json, '$.ai_category')) = ''
                  )
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """

            params = (*eligible_types, int(limit))
            rows = conn.execute(self._sql(query), params).fetchall()
            return [self._item_row_to_dict(row) for row in rows]

    def update_item_extra(self, item_id: int, extra: dict[str, Any]) -> None:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("UPDATE items SET extra_json = ? WHERE id = ?"),
                (json_dumps(extra), int(item_id)),
            )
            conn.commit()

    @staticmethod
    def _item_row_to_dict(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["extra"] = json_loads(result.get("extra_json"))
        if result.get("item_type") == "promotion":
            result["url"] = Repository._normalize_promotion_url(
                str(result.get("url") or ""),
            )
        return result

    @staticmethod
    def _normalize_promotion_url(url: str) -> str:
        if not url.startswith("https://store.epicgames.com/"):
            return url

        parsed = urlparse(url)
        path = (parsed.path or "").strip("/")
        if not path:
            return "https://store.epicgames.com/pt-BR/free-games"

        if path.startswith("pt-BR/p/") or path == "pt-BR/free-games":
            return url

        if path.startswith("pt-BR/"):
            slug = path.removeprefix("pt-BR/").strip("/")
            if slug and slug != "free-games":
                return f"https://store.epicgames.com/pt-BR/p/{slug}"

        return url

    @staticmethod
    def _dedupe_promotions(
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for item in items:
            title = str(item.get("title") or "").strip().lower()
            url = str(item.get("url") or "").strip().lower()
            key = (title, url)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return unique

    def cleanup_duplicate_summaries(self) -> dict[str, int]:
        updated = 0
        scanned = 0

        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql(
                    """
                    SELECT id, title, summary
                    FROM items
                    WHERE summary IS NOT NULL AND trim(summary) <> ''
                    """,
                ),
            ).fetchall()

            for row in rows:
                scanned += 1
                item_id = row["id"]
                title = " ".join(str(row["title"] or "").split()).strip()
                summary = " ".join(str(row["summary"] or "").split()).strip()
                if not title or not summary:
                    continue

                title_low = title.lower().rstrip(" .:-–—")
                summary_low = summary.lower()
                normalized = summary
                if summary_low == title.lower():
                    normalized = ""
                elif summary_low.startswith(title_low):
                    normalized = summary[len(title):].lstrip(" .:-–—").strip()

                if normalized == summary:
                    continue

                conn.execute(
                    self._sql("UPDATE items SET summary = ? WHERE id = ?"),
                    (normalized, item_id),
                )
                updated += 1

            conn.commit()

        return {"scanned": scanned, "updated": updated}

    def delete_old_items(self, retention_days: int = 90) -> dict[str, int]:
        """Delete items and price history older than retention_days."""
        deleted_items = 0
        deleted_history = 0

        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                row = conn.execute(
                    "DELETE FROM items WHERE created_at < NOW() - INTERVAL '%s days' RETURNING id"
                    if False else  # noqa: SIM222
                    self._sql(
                        "DELETE FROM items WHERE created_at < NOW() - INTERVAL '1 day' * ? RETURNING id"
                    ),
                    (retention_days,),
                ).fetchall()
                deleted_items = len(row)

                row2 = conn.execute(
                    self._sql(
                        "DELETE FROM price_history WHERE captured_at < NOW() - INTERVAL '1 day' * ? RETURNING id"
                    ),
                    (retention_days,),
                ).fetchall()
                deleted_history = len(row2)
            else:
                cursor = conn.execute(
                    "DELETE FROM items WHERE datetime(created_at) < datetime('now', ?)",
                    (f"-{retention_days} days",),
                )
                deleted_items = cursor.rowcount or 0

                cursor2 = conn.execute(
                    "DELETE FROM price_history WHERE datetime(captured_at) < datetime('now', ?)",
                    (f"-{retention_days} days",),
                )
                deleted_history = cursor2.rowcount or 0

            conn.commit()

        return {"deleted_items": deleted_items, "deleted_history": deleted_history}

    @staticmethod
    def _normalize_url_for_dedupe(url: str) -> str:
        value = (url or "").strip()
        if not value:
            return ""

        parsed = urlparse(value)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").strip().rstrip("/")
        query = parsed.query or ""

        if query:
            parts = []
            for pair in query.split("&"):
                if not pair or pair.startswith("utm_"):
                    continue
                parts.append(pair)
            query = "&".join(parts)

        canonical = f"{host}{path}".lower()
        if query:
            canonical = f"{canonical}?{query.lower()}"

        return canonical

    @staticmethod
    def _normalize_title_for_dedupe(title: str) -> str:
        normalized = " ".join((title or "").lower().split())
        normalized = normalized.replace("\u2019", "'")
        normalized = normalized.replace("\u2018", "'")
        normalized = normalized.replace("\u201c", '"')
        normalized = normalized.replace("\u201d", '"')
        return normalized.strip()

    @staticmethod
    def _semantic_title_key(title: str) -> str:
        normalized = Repository._normalize_title_for_dedupe(title)
        if not normalized:
            return ""

        tokens = re.findall(r"[a-z0-9à-ÿ]+", normalized)
        filtered = [
            token
            for token in tokens
            if token not in Repository.SEMANTIC_STOPWORDS
        ]
        if len(filtered) < 3:
            return ""

        return " ".join(filtered[:8])

    @classmethod
    def _rank_items(
        cls,
        items: list[dict[str, Any]],
        item_type: str | None,
        q: str | None,
    ) -> list[dict[str, Any]]:
        if q:
            return items

        if item_type not in {"news", "tech_ai", "youtube", "release", "job"}:
            return items

        ranked: list[tuple[float, dict[str, Any]]] = []
        for index, item in enumerate(items):
            extra = item.get("extra")
            if not isinstance(extra, dict):
                extra = {}

            ai_score = int(extra.get("ai_score") or 0)
            ai_category = str(extra.get("ai_category") or "").strip().lower()
            ai_reason = str(extra.get("ai_reason") or "").strip().lower()

            recency_bonus = max(0, 40 - index) * 0.35
            category_bonus = (
                12.0
                if ai_category in cls.PREFERRED_AI_CATEGORIES
                else 0.0
            )
            model_bonus = 8.0 if ai_reason == "local-ai" else 0.0

            rank_score = (
                ai_score * 1.2
                + recency_bonus
                + category_bonus
                + model_bonus
            )
            ranked.append((rank_score, item))

        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked]

    @staticmethod
    def _dedupe_items(
        items: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen_url: set[str] = set()
        seen_title: set[tuple[str, str]] = set()
        seen_semantic: set[tuple[str, str]] = set()

        for item in items:
            item_type = str(item.get("item_type") or "")
            source = str(item.get("source") or "").lower().strip()
            title = Repository._normalize_title_for_dedupe(
                str(item.get("title") or ""),
            )
            semantic_title = Repository._semantic_title_key(title)
            url = Repository._normalize_url_for_dedupe(
                str(item.get("url") or ""),
            )

            url_key = f"{item_type}|{url}" if url else ""
            title_key = (item_type, title)
            source_title_key = (f"{item_type}:{source}", title)
            semantic_key = (item_type, semantic_title)

            if url_key and url_key in seen_url:
                continue
            if title and title_key in seen_title:
                continue
            if title and source_title_key in seen_title:
                continue
            if semantic_title and semantic_key in seen_semantic:
                continue

            if url_key:
                seen_url.add(url_key)
            if title:
                seen_title.add(title_key)
                seen_title.add(source_title_key)
            if semantic_title:
                seen_semantic.add(semantic_key)

            unique.append(item)
            if len(unique) >= limit:
                break

        return unique

    # ==================================================================
    # Custom Feeds CRUD
    # ==================================================================

    def add_custom_feed(self, payload: dict[str, Any]) -> int:
        with get_connection(self.database_target) as conn:
            query = """
                INSERT INTO custom_feeds (name, feed_url, item_type, active)
                VALUES (?, ?, ?, 1)
            """
            if self.is_postgres:
                query += " RETURNING id"
            cursor = conn.execute(
                self._sql(query),
                (
                    payload["name"],
                    payload["feed_url"],
                    payload.get("item_type", "news"),
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def list_custom_feeds(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT * FROM custom_feeds ORDER BY created_at DESC",
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_custom_feed(self, feed_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                rows = conn.execute(
                    self._sql("DELETE FROM custom_feeds WHERE id = ? RETURNING id"),
                    (feed_id,),
                ).fetchall()
                conn.commit()
                return len(rows) > 0
            cursor = conn.execute(
                "DELETE FROM custom_feeds WHERE id = ?", (feed_id,),
            )
            conn.commit()
            return (cursor.rowcount or 0) > 0

    def toggle_custom_feed(self, feed_id: int, active: bool) -> bool:
        val = 1 if active else 0
        if self.is_postgres:
            val = active  # type: ignore[assignment]
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("UPDATE custom_feeds SET active = ? WHERE id = ?"),
                (val, feed_id),
            )
            conn.commit()
            return True

    # ==================================================================
    # Favorites CRUD
    # ==================================================================

    def add_favorite(self, item_id: int, tags: list[str] | None = None) -> int:
        tags_json = json_dumps(tags or [])
        with get_connection(self.database_target) as conn:
            # Check if already favorited
            existing = conn.execute(
                self._sql("SELECT id FROM favorites WHERE item_id = ?"),
                (item_id,),
            ).fetchone()
            if existing:
                return int(existing["id"] if isinstance(existing, dict) else existing[0])
            query = "INSERT INTO favorites (item_id, tags) VALUES (?, ?)"
            if self.is_postgres:
                query += " RETURNING id"
            cursor = conn.execute(self._sql(query), (item_id, tags_json))
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def remove_favorite(self, item_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                rows = conn.execute(
                    self._sql("DELETE FROM favorites WHERE item_id = ? RETURNING id"),
                    (item_id,),
                ).fetchall()
                conn.commit()
                return len(rows) > 0
            cursor = conn.execute(
                "DELETE FROM favorites WHERE item_id = ?", (item_id,),
            )
            conn.commit()
            return (cursor.rowcount or 0) > 0

    def update_favorite_tags(self, item_id: int, tags: list[str]) -> bool:
        tags_json = json_dumps(tags)
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("UPDATE favorites SET tags = ? WHERE item_id = ?"),
                (tags_json, item_id),
            )
            conn.commit()
            return True

    def list_favorites(self, limit: int = 100) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql("""
                    SELECT f.id AS fav_id, f.item_id, f.tags, f.created_at AS fav_created,
                           i.item_type, i.source, i.title, i.url, i.summary,
                           i.image_url, i.published_at, i.extra_json, i.created_at
                    FROM favorites f
                    JOIN items i ON i.id = f.item_id
                    ORDER BY f.created_at DESC
                    LIMIT ?
                """),
                (limit,),
            ).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["extra"] = json_loads(item.get("extra_json"))
                item["tags"] = json_loads(item.get("tags"))
                result.append(item)
            return result

    def get_favorite_ids(self) -> set[int]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute("SELECT item_id FROM favorites").fetchall()
            return {int(r["item_id"] if isinstance(r, dict) else r[0]) for r in rows}

    # ==================================================================
    # Notes CRUD
    # ==================================================================

    def add_note(self, item_id: int, content: str) -> int:
        with get_connection(self.database_target) as conn:
            query = "INSERT INTO notes (item_id, content) VALUES (?, ?)"
            if self.is_postgres:
                query += " RETURNING id"
            cursor = conn.execute(self._sql(query), (item_id, content))
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def update_note(self, note_id: int, content: str) -> bool:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql(
                    "UPDATE notes SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
                ),
                (content, note_id),
            )
            conn.commit()
            return True

    def delete_note(self, note_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                rows = conn.execute(
                    self._sql("DELETE FROM notes WHERE id = ? RETURNING id"),
                    (note_id,),
                ).fetchall()
                conn.commit()
                return len(rows) > 0
            cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            conn.commit()
            return (cursor.rowcount or 0) > 0

    def list_notes(self, item_id: int | None = None) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            if item_id is not None:
                rows = conn.execute(
                    self._sql(
                        "SELECT * FROM notes WHERE item_id = ? ORDER BY created_at DESC"
                    ),
                    (item_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notes ORDER BY created_at DESC LIMIT 100",
                ).fetchall()
            return [dict(r) for r in rows]

    # ==================================================================
    # Service Monitors CRUD
    # ==================================================================

    def add_service_monitor(self, payload: dict[str, Any]) -> int:
        with get_connection(self.database_target) as conn:
            query = """
                INSERT INTO service_monitors (name, url, check_method, expected_status, timeout_seconds)
                VALUES (?, ?, ?, ?, ?)
            """
            if self.is_postgres:
                query += " RETURNING id"
            cursor = conn.execute(
                self._sql(query),
                (
                    payload["name"],
                    payload["url"],
                    payload.get("check_method", "GET"),
                    payload.get("expected_status", 200),
                    payload.get("timeout_seconds", 5),
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def list_service_monitors(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT * FROM service_monitors ORDER BY name",
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_service_monitor(self, monitor_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                rows = conn.execute(
                    self._sql("DELETE FROM service_monitors WHERE id = ? RETURNING id"),
                    (monitor_id,),
                ).fetchall()
                conn.commit()
                return len(rows) > 0
            cursor = conn.execute(
                "DELETE FROM service_monitors WHERE id = ?", (monitor_id,),
            )
            conn.commit()
            return (cursor.rowcount or 0) > 0

    def update_service_monitor_status(
        self, monitor_id: int, status: str, latency_ms: float | None,
    ) -> None:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("""
                    UPDATE service_monitors
                    SET last_status = ?, last_latency_ms = ?, last_checked_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """),
                (status, latency_ms, monitor_id),
            )
            conn.execute(
                self._sql("""
                    INSERT INTO service_monitor_history (monitor_id, status, latency_ms)
                    VALUES (?, ?, ?)
                """),
                (monitor_id, status, latency_ms),
            )
            conn.commit()

    def get_service_monitor_history(
        self, monitor_id: int, limit: int = 50,
    ) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql("""
                    SELECT * FROM service_monitor_history
                    WHERE monitor_id = ?
                    ORDER BY checked_at DESC LIMIT ?
                """),
                (monitor_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ==================================================================
    # Currency Rates
    # ==================================================================

    def upsert_currency_rate(self, pair: str, rate: float, variation: float | None = None) -> None:
        with get_connection(self.database_target) as conn:
            existing = conn.execute(
                self._sql("SELECT id FROM currency_rates WHERE pair = ?"),
                (pair,),
            ).fetchone()
            if existing:
                conn.execute(
                    self._sql("""
                        UPDATE currency_rates
                        SET rate = ?, variation = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE pair = ?
                    """),
                    (rate, variation, pair),
                )
            else:
                conn.execute(
                    self._sql("""
                        INSERT INTO currency_rates (pair, rate, variation)
                        VALUES (?, ?, ?)
                    """),
                    (pair, rate, variation),
                )
            conn.commit()

    def list_currency_rates(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT * FROM currency_rates ORDER BY pair",
            ).fetchall()
            return [dict(r) for r in rows]

    # ==================================================================
    # Daily Digests
    # ==================================================================

    def save_daily_digest(self, digest_date: str, content: str, highlights: list[dict] | None = None) -> int:
        highlights_json = json_dumps(highlights or [])
        with get_connection(self.database_target) as conn:
            existing = conn.execute(
                self._sql("SELECT id FROM daily_digests WHERE digest_date = ?"),
                (digest_date,),
            ).fetchone()
            if existing:
                conn.execute(
                    self._sql("""
                        UPDATE daily_digests
                        SET content = ?, highlights_json = ?
                        WHERE digest_date = ?
                    """),
                    (content, highlights_json, digest_date),
                )
                conn.commit()
                return int(existing["id"] if isinstance(existing, dict) else existing[0])
            query = "INSERT INTO daily_digests (digest_date, content, highlights_json) VALUES (?, ?, ?)"
            if self.is_postgres:
                query += " RETURNING id"
            cursor = conn.execute(self._sql(query), (digest_date, content, highlights_json))
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def get_latest_digest(self) -> dict[str, Any] | None:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                "SELECT * FROM daily_digests ORDER BY digest_date DESC LIMIT 1",
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["highlights"] = json_loads(result.get("highlights_json"))
            return result

    # ==================================================================
    # Push Subscriptions
    # ==================================================================

    def add_push_subscription(self, endpoint: str, keys_json: str) -> int:
        with get_connection(self.database_target) as conn:
            existing = conn.execute(
                self._sql("SELECT id FROM push_subscriptions WHERE endpoint = ?"),
                (endpoint,),
            ).fetchone()
            if existing:
                return int(existing["id"] if isinstance(existing, dict) else existing[0])
            query = "INSERT INTO push_subscriptions (endpoint, keys_json) VALUES (?, ?)"
            if self.is_postgres:
                query += " RETURNING id"
            cursor = conn.execute(self._sql(query), (endpoint, keys_json))
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def remove_push_subscription(self, endpoint: str) -> bool:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                rows = conn.execute(
                    self._sql("DELETE FROM push_subscriptions WHERE endpoint = ? RETURNING id"),
                    (endpoint,),
                ).fetchall()
                conn.commit()
                return len(rows) > 0
            cursor = conn.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,),
            )
            conn.commit()
            return (cursor.rowcount or 0) > 0

    def list_push_subscriptions(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute("SELECT * FROM push_subscriptions").fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["keys"] = json_loads(item.get("keys_json"))
                result.append(item)
            return result

    # ==================================================================
    # Saved Filters
    # ==================================================================

    def add_saved_filter(self, name: str, filter_data: dict[str, Any]) -> int:
        filter_json = json_dumps(filter_data)
        with get_connection(self.database_target) as conn:
            query = "INSERT INTO saved_filters (name, filter_json) VALUES (?, ?)"
            if self.is_postgres:
                query += " RETURNING id"
            cursor = conn.execute(self._sql(query), (name, filter_json))
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def list_saved_filters(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT * FROM saved_filters ORDER BY created_at DESC",
            ).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["filter"] = json_loads(item.get("filter_json"))
                result.append(item)
            return result

    def delete_saved_filter(self, filter_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                rows = conn.execute(
                    self._sql("DELETE FROM saved_filters WHERE id = ? RETURNING id"),
                    (filter_id,),
                ).fetchall()
                conn.commit()
                return len(rows) > 0
            cursor = conn.execute(
                "DELETE FROM saved_filters WHERE id = ?", (filter_id,),
            )
            conn.commit()
            return (cursor.rowcount or 0) > 0

    # ==================================================================
    # Trending Topics Detection
    # ==================================================================

    def get_trending_topics(self, hours: int = 6) -> list[dict[str, Any]]:
        """Compare mention volume between current and previous period."""
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                rows = conn.execute(
                    """
                    WITH current_period AS (
                        SELECT title, source FROM items
                        WHERE created_at >= NOW() - INTERVAL '%s hours'
                    ),
                    previous_period AS (
                        SELECT title, source FROM items
                        WHERE created_at >= NOW() - INTERVAL '%s hours'
                          AND created_at < NOW() - INTERVAL '%s hours'
                    )
                    SELECT 'current' AS period, title FROM current_period
                    UNION ALL
                    SELECT 'previous' AS period, title FROM previous_period
                    """.replace("%s", str(int(hours))).replace(
                        "INTERVAL '%s hours'" % str(int(hours * 2)),
                        f"INTERVAL '{int(hours * 2)} hours'",
                    ),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT 'current' AS period, title FROM items
                    WHERE datetime(created_at) >= datetime('now', ?)
                    UNION ALL
                    SELECT 'previous' AS period, title FROM items
                    WHERE datetime(created_at) >= datetime('now', ?)
                      AND datetime(created_at) < datetime('now', ?)
                    """,
                    (f"-{hours} hours", f"-{hours * 2} hours", f"-{hours} hours"),
                ).fetchall()

        # Word frequency analysis
        current_words: dict[str, int] = {}
        previous_words: dict[str, int] = {}

        for r in rows:
            row = dict(r)
            period = row.get("period", "current")
            title = str(row.get("title") or "").lower()
            words = re.findall(r"[a-zà-ÿ0-9]{3,}", title)
            bucket = current_words if period == "current" else previous_words
            for w in words:
                if w not in self.SEMANTIC_STOPWORDS and len(w) > 3:
                    bucket[w] = bucket.get(w, 0) + 1

        # Find trending words (appeared more in current period)
        trending: list[dict[str, Any]] = []
        for word, count in current_words.items():
            prev = previous_words.get(word, 0)
            if count >= 3 and (prev == 0 or count / max(prev, 1) >= 1.5):
                growth = (count - prev) / max(prev, 1) * 100
                trending.append({
                    "topic": word,
                    "current_count": count,
                    "previous_count": prev,
                    "growth_pct": round(growth, 1),
                })

        trending.sort(key=lambda x: x["current_count"], reverse=True)
        return trending[:15]

    # ==================================================================
    # Dashboard snapshot with new data
    # ==================================================================

    def get_dashboard_snapshot_extended(self) -> dict[str, Any]:
        """Extended snapshot with all new feature data."""
        base = self.get_dashboard_snapshot()
        base["currency_rates"] = self.list_currency_rates()
        base["service_monitors"] = self.list_service_monitors()
        base["daily_digest"] = self.get_latest_digest()
        base["trending_topics"] = self.get_trending_topics()
        base["custom_feeds"] = self.list_custom_feeds()
        base["favorite_ids"] = list(self.get_favorite_ids())
        base["unread_notifications"] = self.count_unread_notifications()
        return base

    # ==================================================================
    # Webhooks CRUD
    # ==================================================================

    def list_webhooks(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT * FROM webhooks ORDER BY created_at DESC",
            ).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["event_types"] = json_loads(item.get("event_types") or "[]")
                result.append(item)
            return result

    def add_webhook(self, data: dict) -> int:
        with get_connection(self.database_target) as conn:
            query = (
                "INSERT INTO webhooks (name, url, event_types, secret, active)"
                " VALUES (?, ?, ?, ?, ?)"
            )
            if self.is_postgres:
                query += " RETURNING id"
            event_types = json_dumps(data.get("event_types", ["alert"]))
            active = data.get("active", True)
            if not self.is_postgres:
                active = 1 if active else 0
            cursor = conn.execute(
                self._sql(query),
                (data["name"], data["url"], event_types, data.get("secret"), active),
            )
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def delete_webhook(self, webhook_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                rows = conn.execute(
                    self._sql("DELETE FROM webhooks WHERE id = ? RETURNING id"),
                    (webhook_id,),
                ).fetchall()
                conn.commit()
                return len(rows) > 0
            cursor = conn.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            conn.commit()
            return (cursor.rowcount or 0) > 0

    def get_active_webhooks(self, event_type: str = "alert") -> list[dict[str, Any]]:
        hooks = self.list_webhooks()
        result = []
        for h in hooks:
            active = h.get("active")
            if active in (True, 1):
                types = h.get("event_types", [])
                if event_type in types or "*" in types:
                    result.append(h)
        return result

    # ==================================================================
    # Shared Dashboards
    # ==================================================================

    def create_shared_dashboard(self, token: str, label: str, expires_at: str) -> int:
        with get_connection(self.database_target) as conn:
            query = (
                "INSERT INTO shared_dashboards (token, label, expires_at)"
                " VALUES (?, ?, ?)"
            )
            if self.is_postgres:
                query += " RETURNING id"
            cursor = conn.execute(self._sql(query), (token, label, expires_at))
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def get_shared_dashboard(self, token: str) -> dict | None:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql("SELECT * FROM shared_dashboards WHERE token = ?"),
                (token,),
            ).fetchone()
            return dict(row) if row else None

    def list_shared_dashboards(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT * FROM shared_dashboards ORDER BY created_at DESC",
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_shared_dashboard(self, share_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                rows = conn.execute(
                    self._sql("DELETE FROM shared_dashboards WHERE id = ? RETURNING id"),
                    (share_id,),
                ).fetchall()
                conn.commit()
                return len(rows) > 0
            cursor = conn.execute("DELETE FROM shared_dashboards WHERE id = ?", (share_id,))
            conn.commit()
            return (cursor.rowcount or 0) > 0

    # ==================================================================
    # Notifications
    # ==================================================================

    def add_notification(self, title: str, message: str, notif_type: str = "info") -> int:
        with get_connection(self.database_target) as conn:
            query = (
                "INSERT INTO notifications (title, message, notif_type)"
                " VALUES (?, ?, ?)"
            )
            if self.is_postgres:
                query += " RETURNING id"
            cursor = conn.execute(self._sql(query), (title, message, notif_type))
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def list_notifications(self, limit: int = 50) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql("SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?"),
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_unread_notifications(self) -> int:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM notifications WHERE read = FALSE",
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM notifications WHERE read = 0",
                ).fetchone()
            return int(dict(row).get("cnt", 0)) if row else 0

    def mark_notification_read(self, notif_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            val = True if self.is_postgres else 1
            if self.is_postgres:
                rows = conn.execute(
                    self._sql("UPDATE notifications SET read = %s WHERE id = %s RETURNING id"),
                    (val, notif_id),
                ).fetchall()
                conn.commit()
                return len(rows) > 0
            conn.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notif_id,))
            conn.commit()
            return True

    def mark_all_notifications_read(self) -> int:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                cursor = conn.execute(
                    "UPDATE notifications SET read = TRUE WHERE read = FALSE",
                )
                conn.commit()
                return cursor.rowcount or 0
            cursor = conn.execute("UPDATE notifications SET read = 1 WHERE read = 0")
            conn.commit()
            return cursor.rowcount or 0

    # ── App Settings ───────────────────────────────────────
    def get_all_settings(self) -> dict[str, str]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
            return {r["key"]: r["value"] for r in rows}

    def get_setting(self, key: str, default: str = "") -> str:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = %s"
                if self.is_postgres else
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                conn.execute(
                    """INSERT INTO app_settings (key, value, updated_at)
                       VALUES (%s, %s, CURRENT_TIMESTAMP)
                       ON CONFLICT (key) DO UPDATE
                       SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP""",
                    (key, value),
                )
            else:
                conn.execute(
                    """INSERT OR REPLACE INTO app_settings (key, value, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP)""",
                    (key, value),
                )
            conn.commit()

    def set_settings_bulk(self, settings: dict[str, str]) -> None:
        with get_connection(self.database_target) as conn:
            for key, value in settings.items():
                if self.is_postgres:
                    conn.execute(
                        """INSERT INTO app_settings (key, value, updated_at)
                           VALUES (%s, %s, CURRENT_TIMESTAMP)
                           ON CONFLICT (key) DO UPDATE
                           SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP""",
                        (key, str(value)),
                    )
                else:
                    conn.execute(
                        """INSERT OR REPLACE INTO app_settings (key, value, updated_at)
                           VALUES (?, ?, CURRENT_TIMESTAMP)""",
                        (key, str(value)),
                    )
            conn.commit()

    def delete_setting(self, key: str) -> bool:
        with get_connection(self.database_target) as conn:
            cur = conn.execute(
                self._sql("DELETE FROM app_settings WHERE key = ?"),
                (key,),
            )
            conn.commit()
            return bool(getattr(cur, "rowcount", 0))

    def delete_settings_by_prefix(self, prefix: str) -> int:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql("SELECT key FROM app_settings WHERE key LIKE ?"),
                (f"{prefix}%",),
            ).fetchall()
            keys = [str(r["key"]) for r in rows]
            deleted = 0
            for key in keys:
                cur = conn.execute(
                    self._sql("DELETE FROM app_settings WHERE key = ?"),
                    (key,),
                )
                deleted += int(getattr(cur, "rowcount", 0) or 0)
            conn.commit()
            return deleted

    def get_fin_transaction_signature(self, asset_id: int | None = None) -> dict[str, Any]:
        with get_connection(self.database_target) as conn:
            if asset_id is None:
                row = conn.execute(
                    self._sql(
                        """
                        SELECT COUNT(*) AS tx_count,
                               MAX(id) AS max_id,
                               MAX(tx_date) AS max_tx_date
                        FROM fin_transactions
                        """,
                    ),
                ).fetchone()
            else:
                row = conn.execute(
                    self._sql(
                        """
                        SELECT COUNT(*) AS tx_count,
                               MAX(id) AS max_id,
                               MAX(tx_date) AS max_tx_date
                        FROM fin_transactions
                        WHERE asset_id = ?
                        """,
                    ),
                    (asset_id,),
                ).fetchone()
            return {
                "tx_count": int((row and row["tx_count"]) or 0),
                "max_id": int((row and row["max_id"]) or 0),
                "max_tx_date": str((row and row["max_tx_date"]) or ""),
            }

    # ==================================================================
    # Financial Dashboard
    # ==================================================================

    # ── Assets ──────────────────────────────────────────────

    def upsert_fin_asset(self, data: dict[str, Any]) -> int:
        with get_connection(self.database_target) as conn:
            existing = conn.execute(
                self._sql("SELECT id FROM fin_assets WHERE symbol = ?"),
                (data["symbol"],),
            ).fetchone()
            if existing:
                conn.execute(
                    self._sql("""
                        UPDATE fin_assets
                        SET name = ?, asset_type = ?, currency = ?,
                            current_price = ?, previous_close = ?,
                            day_change = ?, day_change_pct = ?,
                            market_cap = ?, volume = ?,
                            extra_json = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE symbol = ?
                    """),
                    (
                        data.get("name", ""),
                        data.get("asset_type", "stock"),
                        data.get("currency", "BRL"),
                        data.get("current_price"),
                        data.get("previous_close"),
                        data.get("day_change"),
                        data.get("day_change_pct"),
                        data.get("market_cap"),
                        data.get("volume"),
                        json_dumps(data.get("extra", {})),
                        data["symbol"],
                    ),
                )
                conn.commit()
                return int(existing["id"])
            else:
                q = self._sql("""
                    INSERT INTO fin_assets
                        (symbol, name, asset_type, currency, current_price,
                         previous_close, day_change, day_change_pct,
                         market_cap, volume, extra_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """)
                if self.is_postgres:
                    q += " RETURNING id"
                cursor = conn.execute(
                    q,
                    (
                        data["symbol"],
                        data.get("name", data["symbol"]),
                        data.get("asset_type", "stock"),
                        data.get("currency", "BRL"),
                        data.get("current_price"),
                        data.get("previous_close"),
                        data.get("day_change"),
                        data.get("day_change_pct"),
                        data.get("market_cap"),
                        data.get("volume"),
                        json_dumps(data.get("extra", {})),
                    ),
                )
                conn.commit()
                if self.is_postgres:
                    row = cursor.fetchone()
                    return int(row["id"]) if row else 0
                return int(cursor.lastrowid or 0)

    def list_fin_assets(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT * FROM fin_assets ORDER BY symbol",
            ).fetchall()
            return [dict(r) for r in rows]

    def get_fin_asset(self, asset_id: int) -> dict[str, Any] | None:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql("SELECT * FROM fin_assets WHERE id = ?"),
                (asset_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_fin_asset_by_symbol(self, symbol: str) -> dict[str, Any] | None:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql("SELECT * FROM fin_assets WHERE symbol = ?"),
                (symbol,),
            ).fetchone()
            return dict(row) if row else None

    def delete_fin_asset(self, asset_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("DELETE FROM fin_assets WHERE id = ?"),
                (asset_id,),
            )
            conn.commit()
            return True

    def normalize_fin_asset_types(self) -> dict[str, int]:
        def _looks_like_fii(symbol: str) -> bool:
            s = str(symbol or "").strip().upper()
            return (len(s) >= 5 and s.endswith("11")) or (len(s) >= 6 and s.endswith("11B"))

        assets_updated = 0
        watchlist_updated = 0
        with get_connection(self.database_target) as conn:
            asset_rows = conn.execute(
                self._sql("SELECT id, symbol, asset_type FROM fin_assets ORDER BY id"),
            ).fetchall()
            for row in asset_rows:
                if not _looks_like_fii(str(row["symbol"] or "")):
                    continue
                current_type = str(row["asset_type"] or "").strip().lower()
                if current_type == "fii":
                    continue
                cur = conn.execute(
                    self._sql("UPDATE fin_assets SET asset_type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"),
                    ("fii", int(row["id"])),
                )
                assets_updated += int(getattr(cur, "rowcount", 0) or 0)

            wl_rows = conn.execute(
                self._sql("SELECT id, symbol, asset_type FROM fin_watchlist ORDER BY id"),
            ).fetchall()
            for row in wl_rows:
                if not _looks_like_fii(str(row["symbol"] or "")):
                    continue
                current_type = str(row["asset_type"] or "").strip().lower()
                if current_type == "fii":
                    continue
                cur = conn.execute(
                    self._sql("UPDATE fin_watchlist SET asset_type = ? WHERE id = ?"),
                    ("fii", int(row["id"])),
                )
                watchlist_updated += int(getattr(cur, "rowcount", 0) or 0)

            conn.commit()

        return {
            "assets_updated": assets_updated,
            "watchlist_updated": watchlist_updated,
        }

    def record_fin_asset_price(
        self, asset_id: int, price: float, volume: float | None = None,
    ) -> None:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql(
                    "INSERT INTO fin_asset_history (asset_id, price, volume) "
                    "VALUES (?, ?, ?)"
                ),
                (asset_id, price, volume),
            )
            conn.commit()

    def get_fin_asset_history(
        self, asset_id: int, limit: int = 90,
    ) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            # Latest price snapshot per day for this asset.
            price_rows = conn.execute(
                self._sql("""
                    SELECT DATE(h.captured_at) AS captured_at, h.price
                    FROM fin_asset_history h
                    JOIN (
                        SELECT DATE(captured_at) AS d, MAX(captured_at) AS max_captured_at
                        FROM fin_asset_history
                        WHERE asset_id = ?
                        GROUP BY DATE(captured_at)
                    ) latest
                      ON latest.d = DATE(h.captured_at)
                     AND latest.max_captured_at = h.captured_at
                    WHERE h.asset_id = ?
                    ORDER BY DATE(h.captured_at) DESC
                    LIMIT ?
                """),
                (asset_id, asset_id, limit),
            ).fetchall()
            tx_rows = conn.execute(
                self._sql("""
                    SELECT
                        DATE(tx_date) AS tx_day,
                        SUM(
                            CASE
                                WHEN LOWER(COALESCE(tx_type, 'buy')) = 'buy' THEN quantity
                                ELSE -quantity
                            END
                        ) AS delta_qty
                        ,SUM(
                            CASE
                                WHEN LOWER(COALESCE(tx_type, 'buy')) = 'buy' THEN quantity
                                ELSE 0
                            END
                        ) AS buy_qty
                        ,SUM(
                            CASE
                                WHEN LOWER(COALESCE(tx_type, 'buy')) = 'buy' THEN (quantity * price)
                                ELSE 0
                            END
                        ) AS buy_notional
                    FROM fin_transactions
                    WHERE asset_id = ?
                    GROUP BY DATE(tx_date)
                    ORDER BY DATE(tx_date) ASC
                """),
                (asset_id,),
            ).fetchall()

            price_map = {
                str(row["captured_at"]): float(row["price"] or 0)
                for row in price_rows
                if row["captured_at"]
            }
            tx_map: dict[str, dict[str, float | None]] = {}
            for row in tx_rows:
                day = str(row["tx_day"] or "")
                if not day:
                    continue
                buy_qty = float(row["buy_qty"] or 0)
                buy_notional = float(row["buy_notional"] or 0)
                tx_map[day] = {
                    "delta_qty": float(row["delta_qty"] or 0),
                    "fallback_price": (
                        (buy_notional / buy_qty)
                        if buy_qty > 0
                        else None
                    ),
                }

            all_dates = sorted(set(price_map.keys()) | set(tx_map.keys()))
            if not all_dates:
                return []

            # Compute historical position value (price * quantity-at-date),
            # including early transaction-only dates before market snapshots.
            qty = 0.0
            last_price = None
            timeline = []
            for date_key in all_dates:
                tx_info = tx_map.get(date_key)
                if tx_info:
                    qty += float(tx_info.get("delta_qty") or 0)
                    fallback_price = tx_info.get("fallback_price")
                    if date_key not in price_map and fallback_price is not None:
                        last_price = float(fallback_price)

                if date_key in price_map:
                    last_price = float(price_map[date_key])

                if last_price is None:
                    continue

                value = float(last_price) * max(0.0, qty)
                timeline.append({
                    "asset_id": asset_id,
                    "price": round(value, 6),
                    "captured_at": date_key,
                })

            timeline.sort(key=lambda r: str(r["captured_at"]), reverse=True)
            return timeline[:limit]

    def get_fin_total_history(self, limit: int = 90) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            price_rows = conn.execute(
                self._sql("""
                    SELECT
                        h.asset_id,
                        DATE(h.captured_at) AS captured_at,
                        h.price
                    FROM fin_asset_history h
                    JOIN (
                        SELECT asset_id, DATE(captured_at) AS d, MAX(captured_at) AS max_captured_at
                        FROM fin_asset_history
                        GROUP BY asset_id, DATE(captured_at)
                    ) latest
                      ON latest.asset_id = h.asset_id
                     AND latest.d = DATE(h.captured_at)
                     AND latest.max_captured_at = h.captured_at
                    ORDER BY DATE(h.captured_at) ASC, h.asset_id ASC
                """),
            ).fetchall()
            tx_rows = conn.execute(
                self._sql("""
                    SELECT
                        asset_id,
                        DATE(tx_date) AS tx_day,
                        SUM(
                            CASE
                                WHEN LOWER(COALESCE(tx_type, 'buy')) = 'buy' THEN quantity
                                ELSE -quantity
                            END
                        ) AS delta_qty
                        ,SUM(
                            CASE
                                WHEN LOWER(COALESCE(tx_type, 'buy')) = 'buy' THEN quantity
                                ELSE 0
                            END
                        ) AS buy_qty
                        ,SUM(
                            CASE
                                WHEN LOWER(COALESCE(tx_type, 'buy')) = 'buy' THEN (quantity * price)
                                ELSE 0
                            END
                        ) AS buy_notional
                    FROM fin_transactions
                    GROUP BY asset_id, DATE(tx_date)
                    ORDER BY asset_id ASC, DATE(tx_date) ASC
                """),
            ).fetchall()

            prices_by_date: dict[str, dict[int, float]] = {}
            for row in price_rows:
                date_key = str(row["captured_at"] or "")
                if not date_key:
                    continue
                asset_prices = prices_by_date.setdefault(date_key, {})
                asset_prices[int(row["asset_id"])] = float(row["price"] or 0)

            tx_by_asset: dict[int, list[tuple[str, float, float | None]]] = {}
            for row in tx_rows:
                day = str(row["tx_day"] or "")
                if not day:
                    continue
                aid = int(row["asset_id"])
                buy_qty = float(row["buy_qty"] or 0)
                buy_notional = float(row["buy_notional"] or 0)
                fallback_price = (buy_notional / buy_qty) if buy_qty > 0 else None
                tx_by_asset.setdefault(aid, []).append((
                    day,
                    float(row["delta_qty"] or 0),
                    fallback_price,
                ))

            all_assets = set()
            for per_date in prices_by_date.values():
                all_assets.update(per_date.keys())
            all_assets.update(tx_by_asset.keys())

            all_dates = sorted(
                set(prices_by_date.keys())
                | {
                    day
                    for points in tx_by_asset.values()
                    for (day, _delta, _fallback_price) in points
                }
            )
            if not all_dates:
                return []

            tx_indices = {aid: 0 for aid in all_assets}
            qty_state = {aid: 0.0 for aid in all_assets}
            last_price = {aid: None for aid in all_assets}

            rows: list[dict[str, Any]] = []
            for date_key in all_dates:
                # Apply all transactions up to this date.
                for aid in all_assets:
                    tx_points = tx_by_asset.get(aid, [])
                    idx = tx_indices[aid]
                    while idx < len(tx_points) and tx_points[idx][0] <= date_key:
                        _day, delta_qty, fallback_price = tx_points[idx]
                        qty_state[aid] += float(delta_qty)
                        if aid not in prices_by_date.get(date_key, {}) and fallback_price is not None:
                            last_price[aid] = float(fallback_price)
                        idx += 1
                    tx_indices[aid] = idx

                # Update known prices for this date.
                for aid, price in prices_by_date.get(date_key, {}).items():
                    last_price[aid] = float(price)

                total_value = 0.0
                for aid in all_assets:
                    qty = max(0.0, float(qty_state.get(aid, 0.0)))
                    price = last_price.get(aid)
                    if qty <= 0.0 or price is None:
                        continue
                    total_value += qty * float(price)

                rows.append({
                    "captured_at": date_key,
                    "price": round(total_value, 6),
                })

            rows.sort(key=lambda r: str(r["captured_at"]), reverse=True)
            return rows[:limit]

    # ── Portfolio ───────────────────────────────────────────

    def get_fin_portfolio(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute("""
                SELECT p.*, a.symbol, a.name, a.asset_type, a.currency,
                       a.current_price, a.day_change_pct, a.extra_json
                FROM fin_portfolio p
                JOIN fin_assets a ON a.id = p.asset_id
                ORDER BY p.total_invested DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def upsert_fin_portfolio(
        self, asset_id: int, quantity: float, avg_price: float,
        total_invested: float,
    ) -> None:
        with get_connection(self.database_target) as conn:
            existing = conn.execute(
                self._sql(
                    "SELECT id FROM fin_portfolio WHERE asset_id = ?"
                ),
                (asset_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    self._sql("""
                        UPDATE fin_portfolio
                        SET quantity = ?, avg_price = ?, total_invested = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE asset_id = ?
                    """),
                    (quantity, avg_price, total_invested, asset_id),
                )
            else:
                conn.execute(
                    self._sql("""
                        INSERT INTO fin_portfolio
                            (asset_id, quantity, avg_price, total_invested)
                        VALUES (?, ?, ?, ?)
                    """),
                    (asset_id, quantity, avg_price, total_invested),
                )
            conn.commit()

    def delete_fin_portfolio(self, asset_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("DELETE FROM fin_portfolio WHERE asset_id = ?"),
                (asset_id,),
            )
            conn.commit()
            return True

    # ── Transactions ────────────────────────────────────────

    def is_duplicate_fin_transaction(self, data: dict[str, Any]) -> bool:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql("""
                    SELECT id
                    FROM fin_transactions
                    WHERE asset_id = ?
                      AND tx_type = ?
                      AND quantity = ?
                      AND price = ?
                      AND total = ?
                      AND fees = ?
                      AND tx_date = ?
                      AND COALESCE(notes, '') = COALESCE(?, '')
                    LIMIT 1
                """),
                (
                    data["asset_id"],
                    data.get("tx_type", "buy"),
                    data["quantity"],
                    data["price"],
                    data["total"],
                    data.get("fees", 0),
                    data.get("tx_date"),
                    data.get("notes"),
                ),
            ).fetchone()
            return row is not None

    def cleanup_duplicate_fin_transactions(self) -> dict[str, Any]:
        scanned = 0
        duplicate_rows = 0
        deleted = 0
        touched_asset_ids: set[int] = set()

        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql("""
                    SELECT id, asset_id, tx_type, quantity, price,
                           total, fees, notes, tx_date
                    FROM fin_transactions
                    ORDER BY id ASC
                """),
            ).fetchall()

            scanned = len(rows)
            seen: set[tuple[Any, ...]] = set()
            delete_ids: list[int] = []

            for row in rows:
                key = (
                    int(row["asset_id"]),
                    str(row["tx_type"] or "").strip().lower(),
                    float(row["quantity"] or 0),
                    float(row["price"] or 0),
                    float(row["total"] or 0),
                    float(row["fees"] or 0),
                    str(row["tx_date"] or "").strip(),
                    str(row["notes"] or "").strip(),
                )
                if key in seen:
                    duplicate_rows += 1
                    delete_ids.append(int(row["id"]))
                    touched_asset_ids.add(int(row["asset_id"]))
                    continue
                seen.add(key)

            if delete_ids:
                placeholders = ",".join(["?"] * len(delete_ids))
                conn.execute(
                    self._sql(
                        f"DELETE FROM fin_transactions WHERE id IN ({placeholders})"
                    ),
                    tuple(delete_ids),
                )
                deleted = len(delete_ids)

            conn.commit()

        return {
            "scanned": scanned,
            "duplicates": duplicate_rows,
            "deleted": deleted,
            "touched_asset_ids": sorted(touched_asset_ids),
        }

    def add_fin_transaction(self, data: dict[str, Any]) -> int:
        if self.is_duplicate_fin_transaction(data):
            raise ValueError("Transação duplicada")

        with get_connection(self.database_target) as conn:
            q = self._sql("""
                INSERT INTO fin_transactions
                    (asset_id, tx_type, quantity, price, total, fees, notes, tx_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """)
            if self.is_postgres:
                q += " RETURNING id"
            cursor = conn.execute(
                q,
                (
                    data["asset_id"],
                    data.get("tx_type", "buy"),
                    data["quantity"],
                    data["price"],
                    data["total"],
                    data.get("fees", 0),
                    data.get("notes"),
                    data.get("tx_date", datetime.now(timezone.utc).isoformat()),
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def list_fin_transactions(
        self, asset_id: int | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            if asset_id:
                rows = conn.execute(
                    self._sql("""
                        SELECT t.*, a.symbol, a.name AS asset_name
                        FROM fin_transactions t
                        JOIN fin_assets a ON a.id = t.asset_id
                        WHERE t.asset_id = ?
                        ORDER BY t.tx_date DESC LIMIT ?
                    """),
                    (asset_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    self._sql("""
                        SELECT t.*, a.symbol, a.name AS asset_name
                        FROM fin_transactions t
                        JOIN fin_assets a ON a.id = t.asset_id
                        ORDER BY t.tx_date DESC LIMIT ?
                    """),
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def batch_update_fin_transactions(
        self,
        tx_ids: list[int],
        data: dict[str, Any],
    ) -> int:
        if not tx_ids:
            return 0
        fields = []
        values: list[Any] = []
        allowed = {"tx_type", "quantity", "price", "total", "fees", "notes", "tx_date"}
        for key, val in data.items():
            if key in allowed:
                fields.append(f"{key} = ?")
                values.append(val)
        if not fields:
            return 0
        placeholders = ",".join(["?"] * len(tx_ids))
        with get_connection(self.database_target) as conn:
            cur = conn.execute(
                self._sql(
                    f"UPDATE fin_transactions SET {', '.join(fields)} "
                    f"WHERE id IN ({placeholders})"
                ),
                tuple(values + tx_ids),
            )
            conn.commit()
            return int(cur.rowcount or 0)

    def get_fin_transaction(self, tx_id: int) -> dict[str, Any] | None:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql("SELECT * FROM fin_transactions WHERE id = ?"),
                (tx_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_fin_transaction(self, tx_id: int, data: dict[str, Any]) -> bool:
        fields = []
        values: list = []
        allowed = {"tx_type", "quantity", "price", "total", "fees", "notes", "tx_date"}
        for k, v in data.items():
            if k in allowed:
                fields.append(f"{k} = ?")
                values.append(v)
        if not fields:
            return False
        values.append(tx_id)
        with get_connection(self.database_target) as conn:
            cur = conn.execute(
                self._sql(f"UPDATE fin_transactions SET {', '.join(fields)} WHERE id = ?"),
                values,
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_fin_transaction(self, tx_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("DELETE FROM fin_transactions WHERE id = ?"),
                (tx_id,),
            )
            conn.commit()
            return True

    # ── Watchlist ───────────────────────────────────────────

    def add_fin_watchlist(self, data: dict[str, Any]) -> int:
        with get_connection(self.database_target) as conn:
            # Check for existing entry with same symbol
            existing = conn.execute(
                self._sql("SELECT id FROM fin_watchlist WHERE UPPER(symbol) = UPPER(?)"),
                (data["symbol"],),
            ).fetchone()
            if existing:
                # Update existing watchlist item
                conn.execute(
                    self._sql("""
                        UPDATE fin_watchlist
                        SET name = ?, asset_type = ?, target_price = ?,
                            alert_above = ?, notes = ?
                        WHERE id = ?
                    """),
                    (
                        data.get("name", data["symbol"]),
                        data.get("asset_type", "stock"),
                        data.get("target_price"),
                        bool(data.get("alert_above")),
                        data.get("notes"),
                        existing["id"],
                    ),
                )
                conn.commit()
                return int(existing["id"])
            q = self._sql("""
                INSERT INTO fin_watchlist
                    (symbol, name, asset_type, target_price, alert_above, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """)
            if self.is_postgres:
                q += " RETURNING id"
            cursor = conn.execute(
                q,
                (
                    data["symbol"],
                    data.get("name", data["symbol"]),
                    data.get("asset_type", "stock"),
                    data.get("target_price"),
                    bool(data.get("alert_above")),
                    data.get("notes"),
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def list_fin_watchlist(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT w.*, a.current_price, a.previous_close, "
                "a.day_change, a.day_change_pct "
                "FROM fin_watchlist w "
                "LEFT JOIN fin_assets a ON UPPER(a.symbol) = UPPER(w.symbol) "
                "ORDER BY w.symbol",
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_fin_watchlist(self, wl_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("DELETE FROM fin_watchlist WHERE id = ?"),
                (wl_id,),
            )
            conn.commit()
            return True

    def update_fin_watchlist(self, wl_id: int, data: dict[str, Any]) -> bool:
        fields = []
        values: list = []
        allowed = {"symbol", "name", "asset_type", "target_price", "alert_above", "notes"}
        for k, v in data.items():
            if k in allowed:
                fields.append(f"{k} = ?")
                values.append(v)
        if not fields:
            return False
        values.append(wl_id)
        with get_connection(self.database_target) as conn:
            cur = conn.execute(
                self._sql(f"UPDATE fin_watchlist SET {', '.join(fields)} WHERE id = ?"),
                values,
            )
            conn.commit()
            return cur.rowcount > 0

    # ── Financial Goals ─────────────────────────────────────

    def add_fin_goal(self, data: dict[str, Any]) -> int:
        with get_connection(self.database_target) as conn:
            q = self._sql("""
                INSERT INTO fin_goals
                    (name, target_amount, current_amount, deadline, category, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """)
            if self.is_postgres:
                q += " RETURNING id"
            cursor = conn.execute(
                q,
                (
                    data["name"],
                    data["target_amount"],
                    data.get("current_amount", 0),
                    data.get("deadline"),
                    data.get("category", "savings"),
                    data.get("notes"),
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def list_fin_goals(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT * FROM fin_goals ORDER BY created_at DESC",
            ).fetchall()
            return [dict(r) for r in rows]

    def get_fin_goal(self, goal_id: int) -> dict[str, Any] | None:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql("SELECT * FROM fin_goals WHERE id = ?"),
                (goal_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_fin_goal(self, goal_id: int, data: dict[str, Any]) -> bool:
        with get_connection(self.database_target) as conn:
            fields = []
            values: list[Any] = []
            for key in ("name", "target_amount", "current_amount",
                        "deadline", "category", "notes"):
                if key in data:
                    fields.append(f"{key} = ?")
                    values.append(data[key])
            if not fields:
                return False
            fields.append("updated_at = CURRENT_TIMESTAMP")
            values.append(goal_id)
            conn.execute(
                self._sql(
                    f"UPDATE fin_goals SET {', '.join(fields)} WHERE id = ?"
                ),
                tuple(values),
            )
            conn.commit()
            return True

    def delete_fin_goal(self, goal_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("DELETE FROM fin_goals WHERE id = ?"),
                (goal_id,),
            )
            conn.commit()
            return True

    # ── Cashflow (income/expenses) ─────────────────────────

    def add_fin_cashflow_entry(self, data: dict[str, Any]) -> int:
        with get_connection(self.database_target) as conn:
            q = self._sql(
                """
                INSERT INTO fin_cashflow_entries
                    (entry_type, amount, category, subcategory, cost_center, description, entry_date, notes, tags_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
            )
            if self.is_postgres:
                q += " RETURNING id"
            cursor = conn.execute(
                q,
                (
                    data["entry_type"],
                    data["amount"],
                    data.get("category"),
                    data.get("subcategory"),
                    data.get("cost_center"),
                    data.get("description"),
                    data["entry_date"],
                    data.get("notes"),
                    json_dumps(data.get("tags") or []),
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def list_fin_cashflow_entries(
        self,
        month: str | None = None,
        entry_type: str | None = None,
        payment_status: str | None = None,
        q: str | None = None,
        cost_center: str | None = None,
        subcategory: str | None = None,
        tag: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT e.*, "
            "COALESCE(r.status, CASE WHEN e.entry_type = 'income' THEN 'paid' ELSE 'pending' END) AS payment_status, "
            "r.settled_at, "
            "r.reconciled_at "
            "FROM fin_cashflow_entries e "
            "LEFT JOIN fin_cashflow_reconcile r ON r.entry_id = e.id "
            "WHERE 1=1"
        )
        params: list[Any] = []

        if month:
            query += " AND substr(e.entry_date, 1, 7) = ?"
            params.append(month)

        if entry_type:
            query += " AND e.entry_type = ?"
            params.append(entry_type)

        if payment_status:
            query += (
                " AND COALESCE(r.status, "
                "CASE WHEN e.entry_type = 'income' THEN 'paid' ELSE 'pending' END) = ?"
            )
            params.append(payment_status)

        if cost_center:
            query += " AND LOWER(COALESCE(e.cost_center, '')) = LOWER(?)"
            params.append(cost_center)

        if subcategory:
            query += " AND LOWER(COALESCE(e.subcategory, '')) = LOWER(?)"
            params.append(subcategory)

        if tag:
            query += " AND LOWER(COALESCE(e.tags_json, '')) LIKE ?"
            params.append(f'%"{str(tag or '').lower()}"%')

        if q:
            query += (
                " AND ("
                "LOWER(COALESCE(e.category, '')) LIKE ? "
                "OR LOWER(COALESCE(e.subcategory, '')) LIKE ? "
                "OR LOWER(COALESCE(e.cost_center, '')) LIKE ? "
                "OR LOWER(COALESCE(e.description, '')) LIKE ? "
                "OR LOWER(COALESCE(e.notes, '')) LIKE ? "
                "OR LOWER(COALESCE(e.tags_json, '')) LIKE ?"
                ")"
            )
            q_like = f"%{str(q).lower()}%"
            params.extend([q_like, q_like, q_like, q_like, q_like, q_like])

        query += " ORDER BY e.entry_date DESC, e.created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))

        with get_connection(self.database_target) as conn:
            rows = conn.execute(self._sql(query), tuple(params)).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                rec = dict(row)
                tags = json_loads(rec.get("tags_json") or "[]")
                rec["tags"] = tags if isinstance(tags, list) else []
                out.append(rec)
            return out

    def get_fin_cashflow_entry(self, entry_id: int) -> dict[str, Any] | None:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql("SELECT * FROM fin_cashflow_entries WHERE id = ?"),
                (entry_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_fin_cashflow_entry(self, entry_id: int, data: dict[str, Any]) -> bool:
        fields = []
        values: list[Any] = []
        allowed = {
            "entry_type",
            "amount",
            "category",
            "subcategory",
            "cost_center",
            "description",
            "entry_date",
            "notes",
            "tags",
        }
        for key, value in data.items():
            if key in allowed:
                if key == "tags":
                    fields.append("tags_json = ?")
                    values.append(json_dumps(value or []))
                else:
                    fields.append(f"{key} = ?")
                    values.append(value)
        if not fields:
            return False

        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(entry_id)
        with get_connection(self.database_target) as conn:
            cur = conn.execute(
                self._sql(
                    f"UPDATE fin_cashflow_entries SET {', '.join(fields)} WHERE id = ?"
                ),
                tuple(values),
            )
            conn.commit()
            return bool(cur.rowcount)

    def add_fin_cashflow_attachment(
        self,
        entry_id: int,
        file_name: str,
        mime_type: str,
        file_blob: bytes,
    ) -> int:
        with get_connection(self.database_target) as conn:
            q = self._sql(
                """
                INSERT INTO fin_cashflow_attachments
                    (entry_id, file_name, mime_type, file_size, file_blob)
                VALUES (?, ?, ?, ?, ?)
                """,
            )
            if self.is_postgres:
                q += " RETURNING id"
            cur = conn.execute(
                q,
                (
                    int(entry_id),
                    str(file_name or "arquivo"),
                    str(mime_type or "application/octet-stream"),
                    int(len(file_blob or b"")),
                    file_blob,
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cur.fetchone()
                return int(row["id"]) if row else 0
            return int(cur.lastrowid or 0)

    def list_fin_cashflow_attachments(self, entry_id: int) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql(
                    """
                    SELECT id, entry_id, file_name, mime_type, file_size, created_at
                    FROM fin_cashflow_attachments
                    WHERE entry_id = ?
                    ORDER BY created_at DESC, id DESC
                    """,
                ),
                (int(entry_id),),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_fin_cashflow_attachment(self, attachment_id: int) -> dict[str, Any] | None:
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql(
                    """
                    SELECT id, entry_id, file_name, mime_type, file_size, file_blob, created_at
                    FROM fin_cashflow_attachments
                    WHERE id = ?
                    """,
                ),
                (int(attachment_id),),
            ).fetchone()
            if not row:
                return None
            out = dict(row)
            blob = out.get("file_blob")
            if isinstance(blob, memoryview):
                out["file_blob"] = blob.tobytes()
            return out

    def delete_fin_cashflow_attachment(self, attachment_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            cur = conn.execute(
                self._sql("DELETE FROM fin_cashflow_attachments WHERE id = ?"),
                (int(attachment_id),),
            )
            conn.commit()
            return bool(cur.rowcount)

    def add_fin_cashflow_recurring(self, data: dict[str, Any]) -> int:
        with get_connection(self.database_target) as conn:
            q = self._sql(
                """
                INSERT INTO fin_cashflow_recurring
                    (active, entry_type, amount, category, subcategory, cost_center,
                     description, notes, tags_json, frequency, day_of_month, day_rule,
                     start_date, end_date, last_generated_month)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
            )
            if self.is_postgres:
                q += " RETURNING id"

            active_value: bool | int = bool(data.get("active", True)) if self.is_postgres else (1 if data.get("active", True) else 0)
            cur = conn.execute(
                q,
                (
                    active_value,
                    data["entry_type"],
                    data["amount"],
                    data.get("category"),
                    data.get("subcategory"),
                    data.get("cost_center"),
                    data.get("description"),
                    data.get("notes"),
                    json_dumps(data.get("tags") or []),
                    data.get("frequency", "monthly"),
                    data.get("day_of_month", 1),
                    data.get("day_rule", "exact"),
                    data.get("start_date"),
                    data.get("end_date"),
                    data.get("last_generated_month"),
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cur.fetchone()
                return int(row["id"]) if row else 0
            return int(cur.lastrowid or 0)

    def list_fin_cashflow_recurring(self, active_only: bool = False) -> list[dict[str, Any]]:
        q = "SELECT * FROM fin_cashflow_recurring"
        params: list[Any] = []
        if active_only:
            q += " WHERE active = ?"
            params.append(True if self.is_postgres else 1)
        q += " ORDER BY id DESC"
        with get_connection(self.database_target) as conn:
            rows = conn.execute(self._sql(q), tuple(params)).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                rec = dict(row)
                tags = json_loads(rec.get("tags_json") or "[]")
                rec["tags"] = tags if isinstance(tags, list) else []
                rec["active"] = bool(rec.get("active"))
                out.append(rec)
            return out

    def update_fin_cashflow_recurring(self, recurring_id: int, data: dict[str, Any]) -> bool:
        allowed = {
            "active",
            "entry_type",
            "amount",
            "category",
            "subcategory",
            "cost_center",
            "description",
            "notes",
            "tags",
            "frequency",
            "day_of_month",
            "day_rule",
            "start_date",
            "end_date",
            "last_generated_month",
        }
        fields: list[str] = []
        values: list[Any] = []
        for key, value in data.items():
            if key not in allowed:
                continue
            if key == "tags":
                fields.append("tags_json = ?")
                values.append(json_dumps(value or []))
            elif key == "active":
                if self.is_postgres:
                    fields.append("active = ?")
                    values.append(bool(value))
                else:
                    fields.append("active = ?")
                    values.append(1 if bool(value) else 0)
            else:
                fields.append(f"{key} = ?")
                values.append(value)

        if not fields:
            return False

        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(recurring_id)
        with get_connection(self.database_target) as conn:
            cur = conn.execute(
                self._sql(
                    f"UPDATE fin_cashflow_recurring SET {', '.join(fields)} WHERE id = ?"
                ),
                tuple(values),
            )
            conn.commit()
            return bool(cur.rowcount)

    def delete_fin_cashflow_recurring(self, recurring_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            cur = conn.execute(
                self._sql("DELETE FROM fin_cashflow_recurring WHERE id = ?"),
                (recurring_id,),
            )
            conn.commit()
            return bool(cur.rowcount)

    def run_fin_cashflow_recurring_for_month(self, month: str) -> dict[str, Any]:
        templates = self.list_fin_cashflow_recurring(active_only=True)
        existing = self.list_fin_cashflow_entries(month=month, limit=5000)

        existing_signatures: set[tuple[str, float, str, str, str]] = set()
        for row in existing:
            existing_signatures.add(
                (
                    str(row.get("entry_type") or "").strip().lower(),
                    round(float(row.get("amount") or 0), 2),
                    str(row.get("category") or "").strip().lower(),
                    str(row.get("description") or "").strip().lower(),
                    str(row.get("entry_date") or "")[:10],
                ),
            )

        created_ids: list[int] = []
        skipped_duplicate = 0
        skipped_already_generated = 0

        year = int(month[:4])
        month_num = int(month[5:7])
        days_in_month = calendar.monthrange(year, month_num)[1]

        def _resolve_entry_date(tpl: dict[str, Any]) -> str | None:
            """Resolve entry date in target month based on frequency + day_rule."""
            freq = str(tpl.get("frequency") or "monthly").lower()
            day_rule = str(tpl.get("day_rule") or "exact").lower()
            start_date = str(tpl.get("start_date") or "").strip()
            end_date = str(tpl.get("end_date") or "").strip()

            # Check date bounds
            if start_date and start_date[:7] > month:
                return None
            if end_date and end_date[:7] < month:
                return None

            # For quarterly: run every 3 months from start_date (or from month 1)
            if freq == "quarterly":
                start_m = int(start_date[5:7]) if len(start_date) >= 7 else 1
                start_y = int(start_date[:4]) if len(start_date) >= 7 else year
                # Months elapsed since start
                months_elapsed = (year - start_y) * 12 + (month_num - start_m)
                if months_elapsed < 0 or months_elapsed % 3 != 0:
                    return None
            elif freq == "yearly":
                start_m = int(start_date[5:7]) if len(start_date) >= 7 else month_num
                if month_num != start_m:
                    return None
            elif freq != "monthly":
                return None  # unsupported frequency

            # Resolve exact calendar day
            if day_rule == "last_day":
                day = days_in_month
            elif day_rule == "first_weekday":
                # Find first Monday–Friday of the month
                day = 1
                for d in range(1, days_in_month + 1):
                    if datetime(year, month_num, d).weekday() < 5:
                        day = d
                        break
            elif day_rule == "last_weekday":
                # Find last Monday–Friday of the month
                day = days_in_month
                for d in range(days_in_month, 0, -1):
                    if datetime(year, month_num, d).weekday() < 5:
                        day = d
                        break
            else:
                # exact: use day_of_month, clamp to month length
                day = max(1, min(days_in_month, int(tpl.get("day_of_month") or 1)))

            return f"{year:04d}-{month_num:02d}-{day:02d}"

        for tpl in templates:
            last_month = str(tpl.get("last_generated_month") or "").strip()
            freq = str(tpl.get("frequency") or "monthly").lower()

            # For monthly: skip if already generated this month
            if freq == "monthly" and last_month and last_month >= month:
                skipped_already_generated += 1
                continue
            # For quarterly/yearly: skip if already generated this month
            if freq in ("quarterly", "yearly") and last_month == month:
                skipped_already_generated += 1
                continue

            entry_date = _resolve_entry_date(tpl)
            if entry_date is None:
                continue

            signature = (
                str(tpl.get("entry_type") or "").strip().lower(),
                round(float(tpl.get("amount") or 0), 2),
                str(tpl.get("category") or "").strip().lower(),
                str(tpl.get("description") or "").strip().lower(),
                entry_date,
            )

            if signature in existing_signatures:
                skipped_duplicate += 1
                self.update_fin_cashflow_recurring(int(tpl["id"]), {"last_generated_month": month})
                continue

            new_id = self.add_fin_cashflow_entry(
                {
                    "entry_type": signature[0],
                    "amount": signature[1],
                    "category": str(tpl.get("category") or "").strip(),
                    "subcategory": str(tpl.get("subcategory") or "").strip(),
                    "cost_center": str(tpl.get("cost_center") or "").strip(),
                    "description": str(tpl.get("description") or "").strip(),
                    "entry_date": entry_date,
                    "notes": str(tpl.get("notes") or "").strip(),
                    "tags": tpl.get("tags") if isinstance(tpl.get("tags"), list) else [],
                },
            )
            existing_signatures.add(signature)
            created_ids.append(int(new_id))
            self.update_fin_cashflow_recurring(int(tpl["id"]), {"last_generated_month": month})

        return {
            "month": month,
            "created": len(created_ids),
            "created_ids": created_ids,
            "skipped_duplicate": skipped_duplicate,
            "skipped_already_generated": skipped_already_generated,
            "templates_total": len(templates),
        }

    def get_fin_cashflow_status(self, entry_id: int) -> dict[str, Any]:
        with get_connection(self.database_target) as conn:
            base = conn.execute(
                self._sql("SELECT entry_type FROM fin_cashflow_entries WHERE id = ?"),
                (entry_id,),
            ).fetchone()
            if not base:
                return {}

            default_status = "paid" if str(base["entry_type"] or "") == "income" else "pending"
            row = conn.execute(
                self._sql(
                    """
                    SELECT status, settled_at, reconciled_at
                    FROM fin_cashflow_reconcile
                    WHERE entry_id = ?
                    """,
                ),
                (entry_id,),
            ).fetchone()
            if not row:
                return {
                    "status": default_status,
                    "settled_at": None,
                    "reconciled_at": None,
                }
            rec = dict(row)
            rec["status"] = str(rec.get("status") or default_status)
            return rec

    def set_fin_cashflow_status(
        self,
        entry_id: int,
        status: str,
        settled_at: str | None,
    ) -> bool:
        with get_connection(self.database_target) as conn:
            exists = conn.execute(
                self._sql("SELECT id FROM fin_cashflow_entries WHERE id = ?"),
                (entry_id,),
            ).fetchone()
            if not exists:
                return False

            conn.execute(
                self._sql(
                    """
                    INSERT INTO fin_cashflow_reconcile (entry_id, status, settled_at, reconciled_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(entry_id)
                    DO UPDATE SET
                        status = excluded.status,
                        settled_at = excluded.settled_at,
                        reconciled_at = CURRENT_TIMESTAMP
                    """,
                ),
                (entry_id, status, settled_at),
            )
            conn.commit()
            return True

    def delete_fin_cashflow_entry(self, entry_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("DELETE FROM fin_cashflow_entries WHERE id = ?"),
                (entry_id,),
            )
            conn.commit()
            return True

    def get_fin_cashflow_summary(self, months: int = 6) -> dict[str, Any]:
        safe_months = max(1, min(24, int(months)))
        rows = self.list_fin_cashflow_entries(limit=5000)

        monthly: dict[str, dict[str, float]] = {}
        total_income = 0.0
        total_expense = 0.0

        for row in rows:
            month_key = str(row.get("entry_date") or "")[:7]
            if len(month_key) != 7:
                continue
            amount = float(row.get("amount") or 0)
            entry_type = str(row.get("entry_type") or "")
            bucket = monthly.setdefault(month_key, {"income": 0.0, "expense": 0.0})
            if entry_type == "income":
                bucket["income"] += amount
                total_income += amount
            elif entry_type == "expense":
                bucket["expense"] += amount
                total_expense += amount

        month_keys = sorted(monthly.keys())[-safe_months:]
        monthly_rows: list[dict[str, Any]] = []
        for mk in month_keys:
            inc = float(monthly[mk].get("income") or 0)
            exp = float(monthly[mk].get("expense") or 0)
            monthly_rows.append(
                {
                    "month": mk,
                    "income": round(inc, 2),
                    "expense": round(exp, 2),
                    "balance": round(inc - exp, 2),
                },
            )

        now_month = datetime.now(timezone.utc).strftime("%Y-%m")
        now_inc = float(monthly.get(now_month, {}).get("income") or 0)
        now_exp = float(monthly.get(now_month, {}).get("expense") or 0)

        return {
            "months": safe_months,
            "current_month": now_month,
            "current_income": round(now_inc, 2),
            "current_expense": round(now_exp, 2),
            "current_balance": round(now_inc - now_exp, 2),
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "total_balance": round(total_income - total_expense, 2),
            "monthly": monthly_rows,
        }

    def get_fin_cashflow_budget(self, month: str) -> dict[str, float]:
        key = f"finance_cashflow_budget:{month}"
        raw = self.get_setting(key, "{}")
        parsed = json_loads(raw)
        if not isinstance(parsed, dict):
            return {}

        result: dict[str, float] = {}
        for k, v in parsed.items():
            category = str(k or "").strip()
            if not category:
                continue
            try:
                amount = float(v)
            except (TypeError, ValueError):
                continue
            if not (amount >= 0):
                continue
            result[category] = round(amount, 2)
        return result

    def set_fin_cashflow_budget(self, month: str, budget: dict[str, float]) -> None:
        safe_budget: dict[str, float] = {}
        for k, v in (budget or {}).items():
            category = str(k or "").strip()
            if not category:
                continue
            try:
                amount = float(v)
            except (TypeError, ValueError):
                continue
            if amount < 0:
                continue
            safe_budget[category] = round(amount, 2)

        key = f"finance_cashflow_budget:{month}"
        self.set_setting(key, json_dumps(safe_budget))

    def get_fin_cashflow_analytics(self, month: str | None = None) -> dict[str, Any]:
        target_month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        rows = self.list_fin_cashflow_entries(month=target_month, limit=5000)

        income_total = 0.0
        expense_total = 0.0
        by_income_category: dict[str, float] = {}
        by_expense_category: dict[str, float] = {}
        daily: dict[str, dict[str, float]] = {}

        for row in rows:
            amount = float(row.get("amount") or 0)
            entry_type = str(row.get("entry_type") or "").strip().lower()
            category = str(row.get("category") or "").strip() or "Sem categoria"
            day_key = str(row.get("entry_date") or "")[:10]
            if len(day_key) != 10:
                continue

            day_bucket = daily.setdefault(day_key, {"income": 0.0, "expense": 0.0})
            if entry_type == "income":
                income_total += amount
                by_income_category[category] = by_income_category.get(category, 0.0) + amount
                day_bucket["income"] += amount
            elif entry_type == "expense":
                expense_total += amount
                by_expense_category[category] = by_expense_category.get(category, 0.0) + amount
                day_bucket["expense"] += amount

        balance = income_total - expense_total
        savings_rate_pct = (balance / income_total * 100.0) if income_total > 0 else 0.0

        def _category_rows(src: dict[str, float], total: float) -> list[dict[str, Any]]:
            out = []
            for cat, val in sorted(src.items(), key=lambda item: item[1], reverse=True):
                pct = (val / total * 100.0) if total > 0 else 0.0
                out.append({
                    "category": cat,
                    "amount": round(val, 2),
                    "pct": round(pct, 2),
                })
            return out

        income_categories = _category_rows(by_income_category, income_total)
        expense_categories = _category_rows(by_expense_category, expense_total)

        daily_rows: list[dict[str, Any]] = []
        for day in sorted(daily.keys()):
            inc = float(daily[day].get("income") or 0)
            exp = float(daily[day].get("expense") or 0)
            daily_rows.append(
                {
                    "day": day,
                    "income": round(inc, 2),
                    "expense": round(exp, 2),
                    "balance": round(inc - exp, 2),
                },
            )

        year, month_num = target_month.split("-")
        days_in_month = calendar.monthrange(int(year), int(month_num))[1]
        today = datetime.now(timezone.utc)
        elapsed_days = today.day if target_month == today.strftime("%Y-%m") else days_in_month
        elapsed_days = max(1, min(days_in_month, elapsed_days))

        avg_daily_income = income_total / elapsed_days
        avg_daily_expense = expense_total / elapsed_days
        projected_income = avg_daily_income * days_in_month
        projected_expense = avg_daily_expense * days_in_month
        projected_balance = projected_income - projected_expense

        budget_map = self.get_fin_cashflow_budget(target_month)
        budget_rows: list[dict[str, Any]] = []
        budget_total = 0.0
        budget_spent = 0.0
        for category, limit in sorted(budget_map.items(), key=lambda item: item[0].lower()):
            spent = float(by_expense_category.get(category, 0.0))
            remaining = limit - spent
            usage_pct = (spent / limit * 100.0) if limit > 0 else 0.0
            budget_total += limit
            budget_spent += spent
            budget_rows.append(
                {
                    "category": category,
                    "limit": round(limit, 2),
                    "spent": round(spent, 2),
                    "remaining": round(remaining, 2),
                    "usage_pct": round(usage_pct, 2),
                    "over_budget": spent > limit,
                },
            )

        return {
            "month": target_month,
            "totals": {
                "income": round(income_total, 2),
                "expense": round(expense_total, 2),
                "balance": round(balance, 2),
                "savings_rate_pct": round(savings_rate_pct, 2),
            },
            "projection": {
                "days_in_month": days_in_month,
                "elapsed_days": elapsed_days,
                "projected_income": round(projected_income, 2),
                "projected_expense": round(projected_expense, 2),
                "projected_balance": round(projected_balance, 2),
            },
            "categories": {
                "income": income_categories,
                "expense": expense_categories,
            },
            "daily": daily_rows,
            "top_expenses": expense_categories[:5],
            "budget": {
                "items": budget_rows,
                "total_limit": round(budget_total, 2),
                "total_spent": round(budget_spent, 2),
                "total_remaining": round(budget_total - budget_spent, 2),
            },
        }

    # ── Financial Summary ───────────────────────────────────

    def get_fin_summary(self) -> dict[str, Any]:
        portfolio = self.get_fin_portfolio()
        total_invested = sum(p.get("total_invested", 0) for p in portfolio)
        current_value = sum(
            (p.get("current_price") or 0) * p.get("quantity", 0)
            for p in portfolio
        )
        total_pnl = current_value - total_invested
        total_pnl_pct = (
            (total_pnl / total_invested * 100) if total_invested else 0
        )

        by_type: dict[str, float] = {}
        for p in portfolio:
            atype = p.get("asset_type", "other")
            val = (p.get("current_price") or 0) * p.get("quantity", 0)
            by_type[atype] = by_type.get(atype, 0) + val

        return {
            "total_invested": round(total_invested, 2),
            "current_value": round(current_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "asset_count": len(portfolio),
            "allocation": {
                k: round(v, 2) for k, v in by_type.items()
            },
            "portfolio": portfolio,
        }

    # ── Dividends ───────────────────────────────────────────

    def is_duplicate_fin_dividend(self, data: dict[str, Any]) -> bool:
        key_fields = (
            int(data["asset_id"]),
            str(data.get("div_type", "dividend") or "").strip().lower(),
            float(data.get("amount_per_share", 0) or 0),
            float(data.get("total_amount", 0) or 0),
            float(data.get("quantity", 0) or 0),
            str(data.get("ex_date") or "").strip(),
            str(data.get("pay_date") or "").strip(),
            str(data.get("notes") or "").strip(),
        )
        with get_connection(self.database_target) as conn:
            row = conn.execute(
                self._sql("""
                    SELECT 1 FROM fin_dividends
                    WHERE asset_id=? AND div_type=?
                      AND amount_per_share=? AND total_amount=?
                      AND quantity=? AND (ex_date=? OR (ex_date IS NULL AND ?=''))
                      AND pay_date=?
                      AND (notes=? OR (notes IS NULL AND ?=''))
                    LIMIT 1
                """),
                (
                    key_fields[0], key_fields[1],
                    key_fields[2], key_fields[3],
                    key_fields[4], key_fields[5], key_fields[5],
                    key_fields[6],
                    key_fields[7], key_fields[7],
                ),
            ).fetchone()
        return row is not None

    def cleanup_duplicate_fin_dividends(self) -> dict[str, Any]:
        scanned = 0
        duplicate_rows = 0
        deleted = 0

        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql("""
                    SELECT id, asset_id, div_type, amount_per_share,
                           total_amount, quantity, ex_date, pay_date, notes
                    FROM fin_dividends
                    ORDER BY id ASC
                """),
            ).fetchall()

            scanned = len(rows)
            seen: set[tuple[Any, ...]] = set()
            delete_ids: list[int] = []

            for row in rows:
                key = (
                    int(row["asset_id"]),
                    str(row["div_type"] or "").strip().lower(),
                    float(row["amount_per_share"] or 0),
                    float(row["total_amount"] or 0),
                    float(row["quantity"] or 0),
                    str(row["ex_date"] or "").strip(),
                    str(row["pay_date"] or "").strip(),
                    str(row["notes"] or "").strip(),
                )
                if key in seen:
                    duplicate_rows += 1
                    delete_ids.append(int(row["id"]))
                    continue
                seen.add(key)

            if delete_ids:
                placeholders = ",".join(["?"] * len(delete_ids))
                conn.execute(
                    self._sql(
                        f"DELETE FROM fin_dividends WHERE id IN ({placeholders})"
                    ),
                    tuple(delete_ids),
                )
                deleted = len(delete_ids)

            conn.commit()

        return {
            "scanned": scanned,
            "duplicates": duplicate_rows,
            "deleted": deleted,
        }

    def add_fin_dividend(self, data: dict[str, Any]) -> int:
        if self.is_duplicate_fin_dividend(data):
            raise ValueError("Dividendo duplicado")
        with get_connection(self.database_target) as conn:
            q = self._sql("""
                INSERT INTO fin_dividends
                    (asset_id, div_type, amount_per_share, total_amount,
                     quantity, ex_date, pay_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """)
            if self.is_postgres:
                q += " RETURNING id"
            cursor = conn.execute(
                q,
                (
                    data["asset_id"],
                    data.get("div_type", "dividend"),
                    data.get("amount_per_share", 0),
                    data.get("total_amount", 0),
                    data.get("quantity", 0),
                    data.get("ex_date"),
                    data.get("pay_date"),
                    data.get("notes"),
                ),
            )
            conn.commit()
            if self.is_postgres:
                row = cursor.fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid or 0)

    def list_fin_dividends(
        self, asset_id: int | None = None, limit: int = 200,
    ) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            if asset_id:
                rows = conn.execute(
                    self._sql("""
                        SELECT d.*, a.symbol, a.name AS asset_name
                        FROM fin_dividends d
                        JOIN fin_assets a ON a.id = d.asset_id
                        WHERE d.asset_id = ?
                        ORDER BY d.pay_date DESC LIMIT ?
                    """),
                    (asset_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    self._sql("""
                        SELECT d.*, a.symbol, a.name AS asset_name
                        FROM fin_dividends d
                        JOIN fin_assets a ON a.id = d.asset_id
                        ORDER BY d.pay_date DESC LIMIT ?
                    """),
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def delete_fin_dividend(self, div_id: int) -> bool:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql("DELETE FROM fin_dividends WHERE id = ?"),
                (div_id,),
            )
            conn.commit()
            return True

    def get_fin_dividend_summary(self) -> dict[str, Any]:
        """Get total dividends grouped by asset and type."""
        with get_connection(self.database_target) as conn:
            rows = conn.execute("""
                SELECT a.symbol, d.div_type,
                       SUM(d.total_amount) AS total,
                       COUNT(*) AS count
                FROM fin_dividends d
                JOIN fin_assets a ON a.id = d.asset_id
                GROUP BY a.symbol, d.div_type
                ORDER BY total DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def add_fin_audit_log(
        self,
        action: str,
        target_type: str,
        target_id: int | None,
        payload: dict[str, Any] | None = None,
    ) -> int:
        with get_connection(self.database_target) as conn:
            q = self._sql(
                """
                INSERT INTO fin_audit_logs (action, target_type, target_id, payload_json)
                VALUES (?, ?, ?, ?)
                """
            )
            if self.is_postgres:
                q += " RETURNING id"
            cur = conn.execute(
                q,
                (action, target_type, target_id, json_dumps(payload or {})),
            )
            conn.commit()
            if self.is_postgres:
                row = cur.fetchone()
                return int(row["id"]) if row else 0
            return int(cur.lastrowid or 0)

    def list_fin_audit_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                self._sql(
                    """
                    SELECT id, action, target_type, target_id, payload_json, created_at
                    FROM fin_audit_logs
                    ORDER BY id DESC
                    LIMIT ?
                    """
                ),
                (safe_limit,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                rec = dict(row)
                rec["payload"] = json_loads(rec.get("payload_json") or "{}")
                out.append(rec)
            return out

    # ── Allocation Targets ──────────────────────────────────

    def list_fin_allocation_targets(self) -> list[dict[str, Any]]:
        with get_connection(self.database_target) as conn:
            rows = conn.execute(
                "SELECT * FROM fin_allocation_targets ORDER BY asset_type",
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_fin_allocation_target(
        self, asset_type: str, target_pct: float,
    ) -> None:
        with get_connection(self.database_target) as conn:
            existing = conn.execute(
                self._sql(
                    "SELECT id FROM fin_allocation_targets WHERE asset_type = ?",
                ),
                (asset_type,),
            ).fetchone()
            if existing:
                conn.execute(
                    self._sql("""
                        UPDATE fin_allocation_targets
                        SET target_pct = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE asset_type = ?
                    """),
                    (target_pct, asset_type),
                )
            else:
                conn.execute(
                    self._sql("""
                        INSERT INTO fin_allocation_targets (asset_type, target_pct)
                        VALUES (?, ?)
                    """),
                    (asset_type, target_pct),
                )
            conn.commit()

    def delete_fin_allocation_target(self, asset_type: str) -> bool:
        with get_connection(self.database_target) as conn:
            conn.execute(
                self._sql(
                    "DELETE FROM fin_allocation_targets WHERE asset_type = ?",
                ),
                (asset_type,),
            )
            conn.commit()
            return True

    # ── IR Report Helper ────────────────────────────────────

    def get_fin_ir_report(self, year: int) -> dict[str, Any]:
        """Calculate IR-relevant data for a given year."""
        with get_connection(self.database_target) as conn:
            # All transactions in the year grouped by month
            if self.is_postgres:
                month_expr = "TO_CHAR(t.tx_date, 'YYYY-MM')"
            else:
                month_expr = "SUBSTR(t.tx_date, 1, 7)"

            rows = conn.execute(
                f"""
                SELECT {month_expr} AS month, t.tx_type,
                       a.symbol, a.asset_type, a.name,
                       t.quantity, t.price, t.total, t.fees, t.tx_date
                FROM fin_transactions t
                JOIN fin_assets a ON a.id = t.asset_id
                WHERE {month_expr} LIKE ?
                ORDER BY t.tx_date
                """,
                (f"{year}-%",),
            ).fetchall()
            transactions = [dict(r) for r in rows]

            # Dividends in the year
            divs = conn.execute(
                self._sql("""
                    SELECT d.*, a.symbol, a.name AS asset_name
                    FROM fin_dividends d
                    JOIN fin_assets a ON a.id = d.asset_id
                    WHERE d.pay_date LIKE ?
                    ORDER BY d.pay_date
                """),
                (f"{year}-%",),
            ).fetchall()
            dividends = [dict(r) for r in divs]

        # Calculate monthly sell totals & cost basis
        monthly_sells: dict[str, float] = {}
        positions: dict[str, dict] = {}  # symbol -> {qty, avg_cost}

        for t in transactions:
            sym = t["symbol"]
            if sym not in positions:
                positions[sym] = {"qty": 0.0, "total_cost": 0.0}

            if t["tx_type"] == "buy":
                positions[sym]["qty"] += t["quantity"]
                positions[sym]["total_cost"] += t["total"]
            elif t["tx_type"] == "sell":
                month = t["month"]
                pos = positions[sym]
                avg_cost = (
                    pos["total_cost"] / pos["qty"]
                ) if pos["qty"] > 0 else 0
                sell_qty = min(t["quantity"], pos["qty"])
                sell_total = t["quantity"] * t["price"]
                cost_basis = avg_cost * sell_qty
                month_profit = sell_total - cost_basis - t.get("fees", 0)

                monthly_sells.setdefault(month, {"total": 0.0, "profit": 0.0})
                monthly_sells[month]["total"] += sell_total
                monthly_sells[month]["profit"] += month_profit

                pos["qty"] -= sell_qty
                pos["total_cost"] -= avg_cost * sell_qty

        # DARF calculation: months where sells > R$20k
        darf_months = []
        for month, data in sorted(monthly_sells.items()):
            total = data["total"]
            profit = data["profit"]
            darf_months.append({
                "month": month,
                "total_sell": round(total, 2),
                "profit": round(profit, 2),
                "needs_darf": total > 20000,
            })

        total_dividends = sum(d.get("total_amount", 0) for d in dividends)

        # Current positions for declaration
        final_positions = []
        for sym, pos in positions.items():
            if pos["qty"] > 0:
                final_positions.append({
                    "symbol": sym,
                    "quantity": round(pos["qty"], 6),
                    "avg_cost": round(
                        pos["total_cost"] / pos["qty"], 2,
                    ) if pos["qty"] > 0 else 0,
                    "total_cost": round(pos["total_cost"], 2),
                })

        return {
            "year": year,
            "transactions": transactions,
            "dividends": dividends,
            "total_dividends": round(total_dividends, 2),
            "monthly_sells": darf_months,
            "positions_dec31": sorted(
                final_positions, key=lambda x: x["total_cost"], reverse=True,
            ),
        }


