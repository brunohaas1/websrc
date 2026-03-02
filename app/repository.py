from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
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
                rows_query = """
                SELECT source, extra_json, created_at
                FROM items
                WHERE item_type IN (%s, %s, %s, %s, %s)
                  AND created_at >= NOW() - INTERVAL '24 hours'
                """
            else:
                rows_query = """
                SELECT source, extra_json, created_at
                FROM items
                WHERE item_type IN (?, ?, ?, ?, ?)
                  AND datetime(created_at) >= datetime('now', '-24 hours')
                """

            rows = conn.execute(
                self._sql(rows_query),
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
            extra = json_loads(row.get("extra_json"))
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

            created_at = _to_datetime(row.get("created_at"))
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

            source = str(row.get("source") or "desconhecida").strip().lower()
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
