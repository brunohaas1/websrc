"""Cashflow helpers - extracted utility functions from finance_routes.py."""

import csv
import hashlib
import html
import io
import json
import math
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4


def _normalize_tags(raw_tags: Any) -> list[str]:
    """Normalize tags input to list of strings."""
    from ..security import sanitize_text
    if isinstance(raw_tags, list):
        return [sanitize_text(str(t), 30).strip().lower() for t in raw_tags if t]
    if isinstance(raw_tags, str):
        return [sanitize_text(t.strip(), 30).lower() for t in raw_tags.split(",") if t.strip()]
    return []


def cashflow_dedupe_hash(entry_type: str, amount: float, entry_date: str, description: str) -> str:
    """Generate dedup hash for cashflow entry."""
    key = f"{entry_type}|{amount:.2f}|{entry_date}|{description}".lower()
    return hashlib.md5(key.encode()).hexdigest()


def find_potential_cashflow_duplicate(
    existing_entries: list[dict],
    entry_type: str,
    amount: float,
    entry_date: str,
    description: str,
) -> dict | None:
    """Find potential duplicate entry in list."""
    target_desc_lower = (description or "").lower().strip()
    best_match = None
    best_score = 0.0
    
    for entry in existing_entries:
        if str(entry.get("entry_type") or "") != entry_type:
            continue
        
        entry_amount = float(entry.get("amount") or 0)
        if abs(entry_amount - amount) > 0.01:
            continue
        
        entry_date_str = str(entry.get("entry_date") or "")[:10]
        if entry_date_str != entry_date:
            continue
        
        entry_desc_lower = (str(entry.get("description") or "") or "").lower().strip()
        if not entry_desc_lower or not target_desc_lower:
            continue
        
        # Simple similarity: matching words
        target_words = set(target_desc_lower.split())
        entry_words = set(entry_desc_lower.split())
        if len(target_words) == 0 or len(entry_words) == 0:
            continue
        
        intersection = len(target_words & entry_words)
        union = len(target_words | entry_words)
        score = intersection / union if union > 0 else 0.0
        
        if score > best_score:
            best_score = score
            best_match = {
                "id": entry.get("id"),
                "score": score,
                "confidence": "high" if score >= 0.8 else "medium" if score >= 0.6 else "low",
            }
    
    return best_match if best_score >= 0.5 else None


def tokenize_cashflow_text(text: str) -> list[str]:
    """Tokenize cashflow description for searching."""
    cleaned = re.sub(r"[^\w\s]", " ", str(text or "").lower())
    return [t for t in cleaned.split() if len(t) > 2]


def normalize_cashflow_text(text: str) -> str:
    """Normalize cashflow text for comparison."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def build_reconcile_suggestions(month: str | None = None, min_score: float = 60.0) -> list[dict]:
    """Build suggestions for auto-reconciliation."""
    # Placeholder implementation
    return []


# OCR & Receipt Processing Constants
_OCR_PTBR_FIXES = [
    (re.compile(r"\b0(?=\d{2,}[./])"), "O"),
    (re.compile(r"(?<=[A-ZÀ-Ú])0(?=[A-ZÀ-Ú])"), "O"),
    (re.compile(r"(?<=[a-zà-ú])0(?=[a-zà-ú])"), "o"),
]

_CNAE_CATEGORY_MAP = [
    ("aliment", "Alimentação"),
    ("farmácia", "Saúde"),
    ("transporte", "Transporte"),
    ("vestuário", "Vestuário"),
    ("energia", "Contas"),
    ("telecomunicações", "Assinaturas"),
]

_COL_MAP = {
    "simbolo": "symbol", "símbolo": "symbol", "symbol": "symbol",
    "nome": "name", "name": "name",
    "tipo": "asset_type", "operacao": "tx_type",
    "quantidade": "quantity", "qtd": "quantity",
    "preco": "price", "preço": "price",
    "taxas": "fees", "data": "date", "notas": "notes",
}


def _normalize_col(name: str) -> str:
    """Normalize column header."""
    clean = name.strip().lower().replace(" ", "_").replace("-", "_")
    for a, b in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")]:
        clean = clean.replace(a, b)
    return _COL_MAP.get(clean, clean)


# Bulk operation helpers
def validate_bulk_operation_ids(ids_raw: Any, max_ids: int = 500) -> tuple[bool, list[int], str]:
    """Validate bulk operation IDs."""
    if not isinstance(ids_raw, list):
        return False, [], "ids deve ser uma lista"
    
    if len(ids_raw) > max_ids:
        return False, [], f"Máximo de {max_ids} IDs"
    
    validated: list[int] = []
    for item in ids_raw:
        try:
            validated.append(int(item))
        except (TypeError, ValueError):
            continue
    
    if not validated:
        return False, [], "Nenhum ID válido"
    
    return True, validated, ""


def apply_bulk_cashflow_updates(
    entry_ids: list[int],
    updates: dict[str, Any],
    repo: Any,
) -> dict[str, Any]:
    """Apply bulk updates to cashflow entries."""
    updated = 0
    failed = 0
    errors: list[str] = []
    
    for entry_id in entry_ids:
        try:
            if repo.update_fin_cashflow_entry(entry_id, updates):
                updated += 1
            else:
                failed += 1
                errors.append(f"Entry {entry_id} not found")
        except Exception as e:
            failed += 1
            errors.append(f"Entry {entry_id}: {str(e)}")
    
    return {
        "updated": updated,
        "failed": failed,
        "errors": errors[:10],  # Return first 10 errors
    }


def bulk_delete_cashflow_entries(entry_ids: list[int], repo: Any) -> dict[str, Any]:
    """Delete multiple cashflow entries."""
    deleted = 0
    failed = 0
    errors: list[str] = []
    
    for entry_id in entry_ids:
        try:
            if repo.delete_fin_cashflow_entry(entry_id):
                deleted += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            errors.append(f"Entry {entry_id}: {str(e)}")
    
    return {
        "deleted": deleted,
        "failed": failed,
        "errors": errors[:10],
    }


def evaluate_data_quality_alerts(score: int, issues: list[dict]) -> list[dict]:
    """Evaluate data quality alerts."""
    alerts = []
    if score < 50:
        alerts.append({
            "level": "critical",
            "message": "Data quality score is very low",
            "suggestion": "Review and fix data issues before proceeding",
        })
    elif score < 75:
        alerts.append({
            "level": "warning",
            "message": "Data quality could be improved",
            "suggestion": "Consider resolving some of the issues listed",
        })
    return alerts
