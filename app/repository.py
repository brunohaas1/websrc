from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import urlparse

from .db import get_connection, is_postgres_target
from .utils import json_dumps, json_loads, to_dedup_key

try:
    from psycopg import errors as psycopg_errors  # pyright: ignore
except Exception:  # pragma: no cover - optional import
    psycopg_errors = None


class Repository:
    def __init__(self, database_target: str):
        self.database_target = database_target
        self.is_postgres = is_postgres_target(database_target)

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
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM items WHERE 1=1"
        params: list[Any] = []

        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)

        if q:
            query += " AND (title LIKE ? OR summary LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])

        if self.is_postgres:
            query += (
                " ORDER BY COALESCE("
                "NULLIF(published_at, ''), "
                "to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SSOF')"
                ") DESC LIMIT ?"
            )
        else:
            query += (
                " ORDER BY COALESCE(published_at, created_at) DESC LIMIT ?"
            )
        over_fetch_limit = max(limit * 5, 80)
        params.append(over_fetch_limit)

        with get_connection(self.database_target) as conn:
            rows = conn.execute(self._sql(query), params).fetchall()
            items = [self._item_row_to_dict(row) for row in rows]
            return self._dedupe_items(items, limit)

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

        with get_connection(self.database_target) as conn:
            if self.is_postgres:
                totals_query = """
                SELECT
                    COUNT(*) AS total_items,
                    SUM(
                        CASE
                            WHEN (extra_json::jsonb ->> 'ai_summary')
                                 IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ) AS enriched_items,
                    AVG(
                        CASE
                            WHEN (
                                extra_json::jsonb ->> 'ai_latency_ms'
                            )::float > 0
                            THEN (extra_json::jsonb ->> 'ai_latency_ms')::float
                            ELSE NULL
                        END
                    ) AS avg_ai_latency_ms
                FROM items
                WHERE item_type IN (%s, %s, %s, %s, %s)
                  AND created_at >= NOW() - INTERVAL '24 hours'
                """

                fallback_query = """
                SELECT
                    to_char(
                        date_trunc('hour', created_at),
                        'YYYY-MM-DD HH24:00'
                    )
                        AS hour,
                    COUNT(*) AS total,
                    SUM(
                        CASE
                               WHEN (extra_json::jsonb ->> 'ai_reason')
                                   LIKE 'fallback%'
                            THEN 1
                            ELSE 0
                        END
                    ) AS fallback
                FROM items
                WHERE item_type IN (%s, %s, %s, %s, %s)
                  AND created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY hour
                ORDER BY hour DESC
                LIMIT 12
                """

                source_query = """
                SELECT
                    lower(trim(source)) AS source,
                    SUM(
                        CASE
                               WHEN (extra_json::jsonb ->> 'ai_summary')
                                   IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ) AS enriched_items,
                    SUM(
                        CASE
                               WHEN (extra_json::jsonb ->> 'ai_reason')
                                   = 'local-ai'
                            THEN 1
                            ELSE 0
                        END
                    ) AS model_success
                FROM items
                WHERE item_type IN (%s, %s, %s, %s, %s)
                  AND created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY source
                HAVING SUM(
                    CASE
                        WHEN (extra_json::jsonb ->> 'ai_summary') IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) > 0
                ORDER BY enriched_items DESC
                LIMIT 10
                """

                reason_query = """
                SELECT
                    COALESCE((extra_json::jsonb ->> 'ai_reason'), 'sem-motivo')
                        AS reason,
                    COUNT(*) AS total
                FROM items
                WHERE item_type IN (%s, %s, %s, %s, %s)
                  AND created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY reason
                ORDER BY total DESC
                LIMIT 10
                """
            else:
                totals_query = """
                SELECT
                    COUNT(*) AS total_items,
                    SUM(
                        CASE
                            WHEN json_extract(
                                extra_json,
                                '$.ai_summary'
                            ) IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ) AS enriched_items,
                    AVG(
                        CASE
                            WHEN json_extract(
                                extra_json,
                                '$.ai_latency_ms'
                            ) > 0
                            THEN json_extract(extra_json, '$.ai_latency_ms')
                            ELSE NULL
                        END
                    ) AS avg_ai_latency_ms
                FROM items
                WHERE item_type IN (?, ?, ?, ?, ?)
                  AND datetime(created_at) >= datetime('now', '-24 hours')
                                """
                fallback_query = """
                SELECT
                    strftime('%Y-%m-%d %H:00', created_at) AS hour,
                    COUNT(*) AS total,
                    SUM(
                        CASE
                            WHEN json_extract(extra_json, '$.ai_reason')
                                 LIKE 'fallback%'
                            THEN 1
                            ELSE 0
                        END
                    ) AS fallback
                FROM items
                WHERE item_type IN (?, ?, ?, ?, ?)
                  AND datetime(created_at) >= datetime('now', '-24 hours')
                GROUP BY hour
                ORDER BY hour DESC
                LIMIT 12
                """

                source_query = """
                SELECT
                    lower(trim(source)) AS source,
                    SUM(
                        CASE
                            WHEN json_extract(
                                extra_json,
                                '$.ai_summary'
                            ) IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ) AS enriched_items,
                    SUM(
                        CASE
                            WHEN json_extract(
                                extra_json,
                                '$.ai_reason'
                            ) = 'local-ai'
                            THEN 1
                            ELSE 0
                        END
                    ) AS model_success
                FROM items
                WHERE item_type IN (?, ?, ?, ?, ?)
                  AND datetime(created_at) >= datetime('now', '-24 hours')
                GROUP BY source
                HAVING enriched_items > 0
                ORDER BY enriched_items DESC
                LIMIT 10
                """

                reason_query = """
                SELECT
                    COALESCE(
                        json_extract(extra_json, '$.ai_reason'),
                        'sem-motivo'
                    )
                        AS reason,
                    COUNT(*) AS total
                FROM items
                WHERE item_type IN (?, ?, ?, ?, ?)
                  AND datetime(created_at) >= datetime('now', '-24 hours')
                GROUP BY reason
                ORDER BY total DESC
                LIMIT 10
                """

            totals_row = conn.execute(
                self._sql(totals_query),
                observed_types,
            ).fetchall()

            fallback_rows = conn.execute(
                self._sql(fallback_query),
                observed_types,
            ).fetchall()

            source_rows = conn.execute(
                self._sql(source_query),
                observed_types,
            ).fetchall()

            reason_rows = conn.execute(
                self._sql(reason_query),
                observed_types,
            ).fetchall()

        totals = totals_row[0] if totals_row else {}
        total = int(totals["total_items"] or 0)
        enriched = int(totals["enriched_items"] or 0)
        avg_latency_value = totals["avg_ai_latency_ms"]

        fallback_rate_by_hour = []
        for row in fallback_rows:
            total_hour = int(row["total"] or 0)
            fallback_hour = int(row["fallback"] or 0)
            rate = (fallback_hour / total_hour * 100) if total_hour else 0.0
            fallback_rate_by_hour.append(
                {
                    "hour": row["hour"] or "desconhecida",
                    "fallback_rate": round(rate, 1),
                    "fallback": fallback_hour,
                    "total": total_hour,
                }
            )

        source_accuracy = []
        for row in source_rows:
            enriched_items = int(row["enriched_items"] or 0)
            model_success = int(row["model_success"] or 0)
            success_rate = (
                (model_success / enriched_items) * 100
                if enriched_items
                else 0.0
            )
            source_accuracy.append(
                {
                    "source": row["source"] or "desconhecida",
                    "model_success_rate": round(success_rate, 1),
                    "enriched_items": enriched_items,
                }
            )

        reason_breakdown = []
        for row in reason_rows:
            reason_breakdown.append(
                {
                    "reason": row["reason"] or "sem-motivo",
                    "total": int(row["total"] or 0),
                }
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
    def _dedupe_items(
        items: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen_url: set[str] = set()
        seen_title: set[tuple[str, str]] = set()

        for item in items:
            item_type = str(item.get("item_type") or "")
            source = str(item.get("source") or "").lower().strip()
            title = Repository._normalize_title_for_dedupe(
                str(item.get("title") or ""),
            )
            url = Repository._normalize_url_for_dedupe(
                str(item.get("url") or ""),
            )

            url_key = f"{item_type}|{url}" if url else ""
            title_key = (item_type, title)
            source_title_key = (f"{item_type}:{source}", title)

            if url_key and url_key in seen_url:
                continue
            if title and title_key in seen_title:
                continue
            if title and source_title_key in seen_title:
                continue

            if url_key:
                seen_url.add(url_key)
            if title:
                seen_title.add(title_key)
                seen_title.add(source_title_key)

            unique.append(item)
            if len(unique) >= limit:
                break

        return unique
