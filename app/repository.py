from __future__ import annotations

import sqlite3
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

