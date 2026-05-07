"""Helper functions for cashflow processing (dedup, parsing, import)."""

import csv
import hashlib
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .security import sanitize_text


def normalize_cashflow_text(value: str) -> str:
    """Normalize text for dedup: lowercase, collapse spaces, remove special chars."""
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return text


def cashflow_dedupe_hash(
    entry_type: str,
    amount: float,
    entry_date: str,
    description: str,
) -> str:
    """Generate SHA1-based dedup token (first 16 chars)."""
    payload = "|".join([
        str(entry_type or "").strip().lower(),
        f"{round(float(amount or 0), 2):.2f}",
        str(entry_date or "")[:10],
        normalize_cashflow_text(description),
    ])
    token = hashlib.sha1(
        payload.encode("utf-8", errors="ignore"),
    ).hexdigest()
    return token[:16]


def tokenize_cashflow_text(value: str) -> set[str]:
    """Extract word tokens (>2 chars) for Jaccard similarity."""
    parts = [p for p in normalize_cashflow_text(value).split(" ") if p]
    return {p for p in parts if len(p) > 2}


def calculate_jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Calculate Jaccard index between two sets (0-1)."""
    if not (set_a or set_b):
        return 0.0
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    intersect = len(set_a & set_b)
    return intersect / union


def find_potential_cashflow_duplicate(
    *,
    existing_entries: list[dict],
    entry_type: str,
    amount: float,
    entry_date: str,
    description: str,
) -> dict | None:
    """
    Score existing entries against candidate (0-100).
    Returns best match or None.
    """
    try:
        target_dt = datetime.strptime(entry_date, "%Y-%m-%d")
    except ValueError:
        return None

    target_tokens = tokenize_cashflow_text(description)
    target_hash = cashflow_dedupe_hash(
        entry_type,
        amount,
        entry_date,
        description,
    )
    best: dict | None = None

    for ex in existing_entries:
        ex_type = str(ex.get("entry_type") or "").strip().lower()
        if ex_type != str(entry_type or "").strip().lower():
            continue

        ex_amount = round(float(ex.get("amount") or 0), 2)
        if abs(ex_amount - round(float(amount or 0), 2)) > 0.01:
            continue

        ex_date = str(ex.get("entry_date") or "")[:10]
        try:
            ex_dt = datetime.strptime(ex_date, "%Y-%m-%d")
        except ValueError:
            continue

        day_delta = abs((target_dt - ex_dt).days)
        if day_delta > 3:
            continue

        ex_desc = str(ex.get("description") or "")
        ex_tokens = tokenize_cashflow_text(ex_desc)
        jaccard = calculate_jaccard_similarity(target_tokens, ex_tokens)
        exact_desc = (
            normalize_cashflow_text(ex_desc)
            == normalize_cashflow_text(description)
        )

        score = 40.0
        score += max(0.0, 30.0 - (day_delta * 8.0))
        score += jaccard * 25.0
        if exact_desc:
            score += 10.0

        confidence = (
            "high"
            if score >= 80
            else ("medium" if score >= 60 else "low")
        )
        candidate = {
            "id": int(ex.get("id") or 0),
            "entry_date": ex_date,
            "description": ex_desc,
            "amount": ex_amount,
            "score": round(score, 2),
            "confidence": confidence,
            "dedupe_hash": cashflow_dedupe_hash(
                ex_type,
                ex_amount,
                ex_date,
                ex_desc,
            ),
            "same_hash": (
                target_hash == cashflow_dedupe_hash(
                    ex_type,
                    ex_amount,
                    ex_date,
                    ex_desc,
                )
            ),
        }
        if best is None or float(candidate["score"]) > float(
            best.get("score") or 0.0,
        ):
            best = candidate

    return best


def parse_cashflow_import_candidates(
    filename: str,
    raw_bytes: bytes,
) -> tuple[list[dict], list[dict]]:
    """Parse CSV/OFX and return candidates list + errors list."""
    candidates: list[dict] = []
    errors: list[dict] = []

    if filename.endswith(".csv"):
        text = raw_bytes.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for i, row in enumerate(reader):
            try:
                entry_date = (
                    sanitize_text(
                        str(row.get("date") or row.get("data") or ""),
                        10,
                    ).strip()
                )
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", entry_date):
                    raise ValueError(f"data inválida: {entry_date}")

                raw_amount = str(
                    row.get("amount") or row.get("valor") or "0",
                ).replace(",", ".")
                amount = round(float(raw_amount), 2)
                if amount <= 0:
                    raise ValueError("amount deve ser positivo")

                entry_type_raw = str(
                    row.get("type") or row.get("tipo") or "expense",
                ).strip().lower()
                entry_type = (
                    entry_type_raw
                    if entry_type_raw in ("income", "expense")
                    else "expense"
                )

                category = sanitize_text(
                    str(
                        row.get("category")
                        or row.get("categoria")
                        or "Importado",
                    ),
                    60,
                ).strip()
                description = sanitize_text(
                    str(row.get("description") or row.get("descricao") or ""),
                    200,
                ).strip()

                candidates.append({
                    "entry_type": entry_type,
                    "amount": amount,
                    "category": category,
                    "description": description,
                    "entry_date": entry_date,
                    "notes": "Importado via CSV",
                })
            except (ValueError, TypeError, KeyError) as exc:
                errors.append({"row": i + 2, "error": str(exc)})
        return candidates, errors

    if filename.endswith(".ofx") or filename.endswith(".qfx"):
        text = raw_bytes.decode("utf-8", errors="replace")
        transactions = re.findall(
            r"<STMTTRN>(.*?)</STMTTRN>",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        for i, block in enumerate(transactions):
            try:
                def _ofx_val(tag: str) -> str:
                    m = re.search(
                        rf"<{tag}>\s*([^\n<]+)",
                        block,
                        re.IGNORECASE,
                    )
                    return m.group(1).strip() if m else ""

                raw_amt = _ofx_val("TRNAMT").replace(",", ".")
                amount = float(raw_amt)
                entry_type = "income" if amount >= 0 else "expense"
                amount = round(abs(amount), 2)
                if amount == 0:
                    continue

                raw_date = _ofx_val("DTPOSTED")[:8]
                if len(raw_date) != 8:
                    raise ValueError(f"DTPOSTED inválido: {raw_date}")
                entry_date = (
                    f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                )

                description = sanitize_text(
                    _ofx_val("MEMO")
                    or _ofx_val("NAME")
                    or "OFX",
                    200,
                )
                candidates.append({
                    "entry_type": entry_type,
                    "amount": amount,
                    "category": "Importado",
                    "description": description,
                    "entry_date": entry_date,
                    "notes": "Importado via OFX",
                })
            except (ValueError, TypeError, IndexError) as exc:
                errors.append({"transaction": i + 1, "error": str(exc)})
        return candidates, errors

    raise ValueError("Formato não suportado. Use .csv, .ofx ou .qfx")


def build_reconcile_suggestions(
    rows: list[dict],
    min_score: float,
) -> list[dict]:
    """Build reconciliation suggestions with scoring heuristics."""
    today = datetime.now(timezone.utc).date()
    keyword_pattern = re.compile(
        r"\b(pix|debito|débito|cartao|cartão|boleto|pagamento"
        r"|ifood|uber|99|transferencia|transferência)\b",
        re.IGNORECASE,
    )
    fixed_pattern = re.compile(
        r"\b(aluguel|condominio|condomínio|energia|luz|agua|água"
        r"|internet|telefone|assinatura|fatura)\b",
        re.IGNORECASE,
    )

    suggestions: list[dict] = []
    for row in rows:
        entry_date = str(row.get("entry_date") or "")[:10]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", entry_date):
            continue

        try:
            due = datetime.strptime(entry_date, "%Y-%m-%d").date()
        except ValueError:
            continue

        age_days = (today - due).days
        if age_days < 0:
            continue

        text_blob = " ".join([
            str(row.get("description") or ""),
            str(row.get("notes") or ""),
            str(row.get("category") or ""),
            str(row.get("subcategory") or ""),
            str(row.get("cost_center") or ""),
        ]).lower()
        amount = float(row.get("amount") or 0)

        score = 0.0
        reasons: list[str] = []
        if age_days >= 2:
            score += 35
            reasons.append("vencido há pelo menos 2 dias")
        if age_days >= 7:
            score += 20
            reasons.append("vencido há pelo menos 7 dias")
        if keyword_pattern.search(text_blob):
            score += 25
            reasons.append("descrição sugere pagamento realizado")
        if fixed_pattern.search(text_blob):
            score += 15
            reasons.append("categoria típica de despesa recorrente")
        if amount <= 500:
            score += 10
            reasons.append("valor baixo/moderado")

        if score >= min_score:
            suggestions.append({
                "id": int(row.get("id") or 0),
                "entry_date": entry_date,
                "amount": round(amount, 2),
                "description": str(row.get("description") or ""),
                "category": str(row.get("category") or ""),
                "score": round(score, 2),
                "reasons": reasons,
            })

    suggestions.sort(
        key=lambda s: (
            -(float(s.get("score") or 0)),
            str(s.get("entry_date") or ""),
        ),
    )
    return suggestions
