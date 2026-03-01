from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import urlparse

from .db import get_connection
from .utils import json_dumps, json_loads, to_dedup_key


class Repository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    def upsert_item(self, item: dict[str, Any]) -> bool:
        dedup_key = to_dedup_key(
            item_type=item["item_type"],
            source=item["source"],
            url=item["url"],
            title=item["title"],
        )
        with get_connection(self.database_path) as conn:
            try:
                conn.execute(
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
            except sqlite3.IntegrityError:
                return False

    def item_exists(self, item: dict[str, Any]) -> bool:
        dedup_key = to_dedup_key(
            item_type=item["item_type"],
            source=item["source"],
            url=item["url"],
            title=item["title"],
        )
        with get_connection(self.database_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM items WHERE dedup_key = ? LIMIT 1",
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

        query += " ORDER BY COALESCE(published_at, created_at) DESC LIMIT ?"
        over_fetch_limit = max(limit * 5, 80)
        params.append(over_fetch_limit)

        with get_connection(self.database_path) as conn:
            rows = conn.execute(query, params).fetchall()
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

        with get_connection(self.database_path) as conn:
            totals_row = conn.execute(
                """
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
                """,
                observed_types,
            ).fetchall()

            fallback_rows = conn.execute(
                """
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
                """,
                observed_types,
            ).fetchall()

            source_rows = conn.execute(
                """
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
                """,
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
        }

    def add_price_watch(self, payload: dict[str, Any]) -> int:
        with get_connection(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO price_watches (
                    name,
                    product_url,
                    css_selector,
                    target_price,
                    currency,
                    active
                )
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    payload["name"],
                    payload["product_url"],
                    payload.get("css_selector"),
                    payload["target_price"],
                    payload.get("currency", "BRL"),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def list_price_watches(self) -> list[dict[str, Any]]:
        with get_connection(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM price_watches
                ORDER BY updated_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def record_price(self, watch_id: int, price: float) -> None:
        with get_connection(self.database_path) as conn:
            conn.execute(
                "INSERT INTO price_history (watch_id, price) VALUES (?, ?)",
                (watch_id, price),
            )
            conn.execute(
                """
                UPDATE price_watches
                SET last_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (price, watch_id),
            )
            conn.commit()

    def get_price_history(
        self,
        watch_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with get_connection(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT watch_id, price, captured_at
                FROM price_history
                WHERE watch_id = ?
                ORDER BY captured_at DESC
                LIMIT ?
                """,
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
        with get_connection(self.database_path) as conn:
            conn.execute(
                """
                INSERT INTO alerts (alert_type, title, message, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (alert_type, title, message, json_dumps(payload or {})),
            )
            conn.commit()

    def list_alerts(self, limit: int = 30) -> list[dict[str, Any]]:
        with get_connection(self.database_path) as conn:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?",
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
    def _item_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
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
