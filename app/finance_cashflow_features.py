"""New cashflow features: bulk operations, smart cache, alerts."""

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from flask import jsonify, request
from flask_limiter import Limiter

from .cache import get_cache
from .repository import Repository
from .security import sanitize_text

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# CACHE INTELIGENTE PARA DEDUPLICATAS
# ──────────────────────────────────────────────────────────

class SmartDedupeCache:
    """
    Multi-backend dedup cache with Redis fallback, TTL, and per-route metrics.
    Supports Redis (if available) with automatic memory fallback.
    """

    def __init__(
        self,
        backend_cache: Any,
        ttl_seconds: int = 3600,
        prefix: str = "cashflow:dedup:",
    ):
        """
        Initialize cache with backend (Redis or Memory) and TTL.
        
        Args:
            backend_cache: Cache instance (RedisJSONCache or MemoryTTLCache)
            ttl_seconds: TTL in seconds (default 1 hour)
            prefix: Key prefix for dedup entries
        """
        self._backend = backend_cache
        self.ttl = ttl_seconds
        self.prefix = prefix
        
        # Local stats tracking (thread-safe)
        self._stats_lock = Lock()
        self._stats: dict[str, dict] = {}
    
    def _record_hit(self, operation: str = "default") -> None:
        """Track a cache hit for an operation."""
        with self._stats_lock:
            if operation not in self._stats:
                self._stats[operation] = {"hits": 0, "misses": 0}
            self._stats[operation]["hits"] += 1
    
    def _record_miss(self, operation: str = "default") -> None:
        """Track a cache miss for an operation."""
        with self._stats_lock:
            if operation not in self._stats:
                self._stats[operation] = {"hits": 0, "misses": 0}
            self._stats[operation]["misses"] += 1

    def get(
        self,
        key: str,
        operation: str = "default",
    ) -> Any | None:
        """
        Get value from cache (Redis or fallback memory).
        Returns None if key expired or missing.
        """
        full_key = f"{self.prefix}{key}"
        try:
            value = self._backend.get(full_key)
            if value is not None:
                self._record_hit(operation)
                return value
            self._record_miss(operation)
            return None
        except Exception as exc:
            logger.warning(
                "Cache get failed for key %s: %s",
                full_key,
                exc,
            )
            self._record_miss(operation)
            return None

    def set(
        self,
        key: str,
        value: Any,
        operation: str = "default",
    ) -> None:
        """Store value in cache with TTL."""
        full_key = f"{self.prefix}{key}"
        try:
            self._backend.set(full_key, value, self.ttl)
        except Exception as exc:
            logger.warning(
                "Cache set failed for key %s: %s",
                full_key,
                exc,
            )

    def stats(self) -> dict:
        """Return hit/miss statistics by operation and overall."""
        with self._stats_lock:
            by_operation = {}
            total_hits = 0
            total_misses = 0
            
            for op, stats in self._stats.items():
                hits = int(stats.get("hits") or 0)
                misses = int(stats.get("misses") or 0)
                total = hits + misses
                hit_rate = (hits / total if total > 0 else 0.0)
                
                by_operation[op] = {
                    "hits": hits,
                    "misses": misses,
                    "total": total,
                    "hit_rate": round(hit_rate, 4),
                }
                total_hits += hits
                total_misses += misses
            
            total = total_hits + total_misses
            overall_hit_rate = (
                total_hits / total if total > 0 else 0.0
            )
            
            return {
                "hits": total_hits,
                "misses": total_misses,
                "total": total,
                "hit_rate": round(overall_hit_rate, 4),
                "ttl_seconds": self.ttl,
                "prefix": self.prefix,
                "by_operation": by_operation,
            }

    def clear(self) -> None:
        """Clear entire cache by prefix."""
        try:
            self._backend.delete_prefix(self.prefix)
        except Exception as exc:
            logger.warning("Cache clear failed: %s", exc)
        
        with self._stats_lock:
            self._stats.clear()


# ──────────────────────────────────────────────────────────
# BULK OPERATIONS
# ──────────────────────────────────────────────────────────

def validate_bulk_operation_ids(
    ids_raw: list,
    max_ids: int = 500,
) -> tuple[bool, list[int], str]:
    """Validate and normalize bulk operation IDs."""
    if not isinstance(ids_raw, list):
        return False, [], "ids deve ser um array"

    if len(ids_raw) == 0:
        return False, [], "ids não pode estar vazio"

    if len(ids_raw) > max_ids:
        return False, [], f"máximo {max_ids} IDs por operação"

    try:
        validated = sorted({int(x) for x in ids_raw if int(x) > 0})
        if not validated:
            return False, [], "nenhum ID válido"
        return True, validated, ""
    except (TypeError, ValueError):
        return False, [], "IDs devem ser números inteiros"


def apply_bulk_cashflow_updates(
    *,
    entry_ids: list[int],
    updates: dict[str, Any],
    repo: Repository,
) -> dict[str, Any]:
    """Apply bulk updates to cashflow entries and return result."""
    if not entry_ids or not updates:
        return {
            "ok": False,
            "updated": 0,
            "errors": "entry_ids e updates são obrigatórios",
        }

    updated = 0
    failed = 0
    error_log: list[dict] = []

    # Fetch all entries once
    all_entries = repo.list_fin_cashflow_entries(limit=5000)
    by_id = {int(e["id"] or 0): e for e in all_entries}

    for eid in entry_ids:
        entry = by_id.get(eid)
        if not entry:
            failed += 1
            error_log.append({
                "id": eid,
                "error": "Entrada não encontrada",
            })
            continue

        try:
            # Build update payload with validation
            payload: dict[str, Any] = {}
            status_to_set: str | None = None
            settled_at: str | None = None

            if "category" in updates:
                category = sanitize_text(
                    str(updates["category"]),
                    60,
                ).strip()
                if category:
                    payload["category"] = category

            if "subcategory" in updates:
                subcategory = sanitize_text(
                    str(updates["subcategory"]),
                    60,
                ).strip()
                if subcategory:
                    payload["subcategory"] = subcategory

            if "cost_center" in updates:
                cost_center = sanitize_text(
                    str(updates["cost_center"]),
                    60,
                ).strip()
                if cost_center:
                    payload["cost_center"] = cost_center

            if "payment_status" in updates:
                status = str(updates["payment_status"]).strip().lower()
                if status in ("pending", "paid"):
                    status_to_set = status

            if "status" in updates and status_to_set is None:
                status = str(updates["status"]).strip().lower()
                if status in ("pending", "paid"):
                    status_to_set = status

            if status_to_set is not None:
                settled_raw = sanitize_text(
                    str(updates.get("settled_at", "")),
                    10,
                ).strip()
                if settled_raw:
                    settled_at = settled_raw
                elif status_to_set == "paid":
                    settled_at = str(entry.get("entry_date") or "")[:10]

            if "notes_append" in updates:
                notes = sanitize_text(
                    str(updates["notes_append"]),
                    500,
                ).strip()
                if notes:
                    current = str(entry.get("notes") or "").strip()
                    payload["notes"] = (
                        f"{current} | {notes}"
                        if current
                        else notes
                    )[:500]

            if "notes" in updates and "notes" not in payload:
                notes = sanitize_text(
                    str(updates["notes"]),
                    500,
                ).strip()
                if notes:
                    payload["notes"] = notes

            if "tags" in updates and isinstance(
                updates.get("tags"),
                list,
            ):
                # Normalize tags
                tags = [
                    sanitize_text(str(t), 30).lower()
                    for t in updates["tags"]
                ]
                tags = [t for t in tags if t][:10]
                if tags:
                    payload["tags"] = tags

            if not payload and status_to_set is None:
                failed += 1
                error_log.append({
                    "id": eid,
                    "error": "Nenhuma atualização válida",
                })
                continue

            changed = False
            if payload:
                ok = repo.update_fin_cashflow_entry(eid, payload)
                if ok:
                    changed = True
                else:
                    failed += 1
                    error_log.append({
                        "id": eid,
                        "error": "Falha ao atualizar no BD",
                    })
                    continue

            if status_to_set is not None:
                ok = repo.set_fin_cashflow_status(
                    eid,
                    status_to_set,
                    settled_at,
                )
                if ok:
                    changed = True
                else:
                    failed += 1
                    error_log.append({
                        "id": eid,
                        "error": "Falha ao atualizar status",
                    })
                    continue

            if changed:
                updated += 1
            else:
                failed += 1
                error_log.append({
                    "id": eid,
                    "error": "Nenhuma atualização aplicada",
                })
        except Exception as exc:
            failed += 1
            error_log.append({
                "id": eid,
                "error": str(exc),
            })

    return {
        "ok": True,
        "updated": updated,
        "failed": failed,
        "total_requested": len(entry_ids),
        "errors": error_log if error_log else None,
    }


def bulk_delete_cashflow_entries(
    *,
    entry_ids: list[int],
    repo: Repository,
) -> dict[str, Any]:
    """Delete multiple cashflow entries."""
    if not entry_ids:
        return {"ok": False, "deleted": 0, "error": "IDs vazio"}

    deleted = 0
    failed = 0
    error_log: list[dict] = []

    for eid in entry_ids:
        try:
            ok = repo.delete_fin_cashflow_entry(eid)
            if ok:
                deleted += 1
            else:
                failed += 1
                error_log.append({"id": eid, "error": "Falha ao deletar"})
        except Exception as exc:
            failed += 1
            error_log.append({"id": eid, "error": str(exc)})

    return {
        "ok": True,
        "deleted": deleted,
        "failed": failed,
        "total_requested": len(entry_ids),
        "errors": error_log if error_log else None,
    }


# ──────────────────────────────────────────────────────────
# DATA QUALITY ALERTS
# ──────────────────────────────────────────────────────────

def evaluate_data_quality_alerts(
    *,
    score: int,
    issues: list[dict],
) -> dict[str, Any]:
    """
    Convert data quality score and issues into actionable alerts.
    
    Returns severity level, action items, and recommendations.
    """
    alerts: list[dict] = []

    if score < 50:
        severity = "critical"
    elif score < 70:
        severity = "warning"
    elif score < 90:
        severity = "info"
    else:
        severity = "healthy"

    # Map issues to alert actions
    for issue in issues:
        code = issue.get("code")
        count = int(issue.get("count") or 0)
        issue_severity = issue.get("severity", "ok")

        if code == "missing_category" and count > 0:
            alerts.append({
                "code": "categorize_entries",
                "severity": "high",
                "count": count,
                "message": f"Categorize {count} entrada(s) sem categoria",
                "action": (
                    "PATCH /api/finance/cashflow/bulk "
                    "com 'category' para os IDs"
                ),
            })

        elif code == "missing_description" and count > 0:
            alerts.append({
                "code": "describe_entries",
                "severity": "medium",
                "count": count,
                "message": f"Descreva {count} entrada(s) sem descrição",
                "action": "Use 'notes_append' em bulk para adicionar",
            })

        elif code == "duplicates" and count > 0:
            alerts.append({
                "code": "resolve_duplicates",
                "severity": "high",
                "count": count,
                "message": f"{count} possível(eis) duplicata(s) detectada(s)",
                "action": (
                    "Use /api/finance/cashflow/dedupe-merge "
                    "para consolidar"
                ),
            })

        elif code == "future_dates" and count > 0:
            alerts.append({
                "code": "fix_future_dates",
                "severity": "medium",
                "count": count,
                "message": f"{count} lançamento(s) com data futura",
                "action": "Verifique se as datas estão corretas",
            })

        elif code == "outliers" and count > 0:
            alerts.append({
                "code": "review_outliers",
                "severity": "low",
                "count": count,
                "message": f"{count} despesa(s) fora do padrão",
                "action": (
                    "Valide categorização de despesas anômalas "
                    "para evitar distorção"
                ),
            })

    return {
        "score": score,
        "severity": severity,
        "total_alerts": len(alerts),
        "alerts": alerts,
        "recommendations": _get_quality_recommendations(
            score,
            severity,
        ),
    }


def _get_quality_recommendations(
    score: int,
    severity: str,
) -> list[str]:
    """Generate recommendations based on score and severity."""
    recs: list[str] = []

    if severity == "critical":
        recs.append(
            "Dados incompletos. Complete categorias e descrições "
            "antes de fechar o mês.",
        )
        recs.append(
            "Resolva duplicatas para evitar duplicação de registros.",
        )

    elif severity == "warning":
        recs.append(
            "Revise categorias e descrições nos próximos dias.",
        )
        recs.append(
            "Valide transações pendentes para garantir acurácia.",
        )

    elif severity == "info":
        recs.append(
            "Dados em bom estado. Pequenos ajustes podem melhorar "
            "ainda mais a qualidade.",
        )

    recs.append("Use filtros salvos para análises recorrentes.")

    return recs
