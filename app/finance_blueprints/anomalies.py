"""Finance anomaly detection routes."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from ..security import require_finance_key


def register_anomaly_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    _fmt_brl = helpers.get("_fmt_brl", lambda value: str(value))

    from flask import jsonify

    @app.get("/api/finance/anomalies")
    @limiter.limit("20/minute")
    def finance_anomalies():
        """
        Detect anomalous transactions using Z-score per category over last 6 months.
        Also flags: duplicate-like amounts within 3 days, single entries > 3× category mean.
        Returns a ranked list of anomalies with severity and explanation.
        """
        cache_key = "finance:anomalies"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)
        try:
            now = datetime.now(timezone.utc)
            current_month = now.strftime("%Y-%m")

            months: list[str] = []
            for i in range(7):
                d = now.replace(day=1) - timedelta(days=1) * (i * 30)
                months.append(d.strftime("%Y-%m"))
            date_from = (now.replace(day=1) - timedelta(days=185)).strftime("%Y-%m-01")

            all_entries = repo.list_fin_cashflow_entries(
                entry_type="expense",
                date_from=date_from,
                limit=10000,
            )

            hist: dict[str, list[float]] = {}
            current_cat: dict[str, list[dict]] = {}
            monthly_totals: dict[str, dict[str, float]] = {}
            for entry in all_entries:
                month = str(entry.get("entry_date") or "")[:7]
                if len(month) != 7:
                    continue
                category = str(entry.get("category") or "Sem categoria")
                amount = float(entry.get("amount") or 0)
                monthly_totals.setdefault(month, {}).setdefault(category, 0.0)
                monthly_totals[month][category] += amount
                if month == current_month:
                    current_cat.setdefault(category, []).append(entry)

            for month, categories in monthly_totals.items():
                if month == current_month:
                    continue
                for category, total in categories.items():
                    hist.setdefault(category, []).append(total)

            anomalies: list[dict] = []

            for category, entries in current_cat.items():
                cur_total = sum(float(entry.get("amount") or 0) for entry in entries)
                history = hist.get(category, [])
                if len(history) < 2:
                    continue
                mean = sum(history) / len(history)
                variance = sum((value - mean) ** 2 for value in history) / len(history)
                std = variance ** 0.5
                if std < 0.01:
                    continue
                z_score = (cur_total - mean) / std
                if z_score > 2.0:
                    severity = "high" if z_score > 3.0 else "medium"
                    pct = ((cur_total - mean) / mean * 100) if mean > 0 else 0
                    anomalies.append({
                        "type": "category_spike",
                        "severity": severity,
                        "category": category,
                        "current_total": round(cur_total, 2),
                        "historical_mean": round(mean, 2),
                        "z_score": round(z_score, 2),
                        "pct_above_mean": round(pct, 1),
                        "title": f"Gastos em '{category}' muito acima do normal",
                        "body": f"Este mês: {_fmt_brl(cur_total)} vs média histórica {_fmt_brl(mean)} (+{pct:.0f}%). Z-score: {z_score:.1f}",
                        "icon": "📊",
                        "entry_ids": [entry["id"] for entry in entries if entry.get("id")],
                    })

            for entry in all_entries:
                month = str(entry.get("entry_date") or "")[:7]
                if month != current_month:
                    continue
                category = str(entry.get("category") or "Sem categoria")
                amount = float(entry.get("amount") or 0)
                history = hist.get(category, [])
                if not history:
                    continue
                cat_mean = sum(history) / len(history)
                if cat_mean < 10:
                    continue
                n_months = max(len(history), 1)
                avg_entries_per_month = max(
                    len([
                        value for value in all_entries
                        if str(value.get("entry_date") or "")[:7] != current_month
                        and str(value.get("category") or "") == category
                    ]) / n_months,
                    1,
                )
                per_entry_mean = cat_mean / avg_entries_per_month
                if per_entry_mean < 10:
                    continue
                if amount > per_entry_mean * 3:
                    severity = "high" if amount > per_entry_mean * 5 else "medium"
                    anomalies.append({
                        "type": "large_transaction",
                        "severity": severity,
                        "category": category,
                        "amount": round(amount, 2),
                        "per_entry_mean": round(per_entry_mean, 2),
                        "description": str(entry.get("description") or ""),
                        "entry_date": str(entry.get("entry_date") or ""),
                        "title": f"Transação grande em '{category}'",
                        "body": f"{entry.get('description') or 'Sem descrição'} — {_fmt_brl(amount)} em {str(entry.get('entry_date') or '')[:10]} (média por lançamento: {_fmt_brl(per_entry_mean)})",
                        "icon": "💸",
                        "entry_ids": [entry["id"]] if entry.get("id") else [],
                    })

            current_entries = [
                entry for entry in all_entries
                if str(entry.get("entry_date") or "")[:7] == current_month
            ]
            seen: list[dict] = []
            for entry in current_entries:
                amount = round(float(entry.get("amount") or 0), 2)
                category = str(entry.get("category") or "")
                try:
                    from datetime import date as _date
                    current_date = _date.fromisoformat(str(entry.get("entry_date") or "")[:10])
                except Exception:
                    continue
                for previous in seen:
                    if round(float(previous.get("amount") or 0), 2) != amount:
                        continue
                    if str(previous.get("category") or "") != category:
                        continue
                    try:
                        previous_date = _date.fromisoformat(str(previous.get("entry_date") or "")[:10])
                    except Exception:
                        continue
                    if abs((current_date - previous_date).days) <= 3:
                        anomalies.append({
                            "type": "duplicate_suspect",
                            "severity": "low",
                            "category": category,
                            "amount": amount,
                            "entry_date": str(entry.get("entry_date") or "")[:10],
                            "description": str(entry.get("description") or ""),
                            "title": f"Possível duplicata em '{category}'",
                            "body": f"Lançamento de {_fmt_brl(amount)} em {str(entry.get('entry_date') or '')[:10]} parece duplicado (mesmo valor/categoria em {str(previous.get('entry_date') or '')[:10]}).",
                            "icon": "🔁",
                            "entry_ids": [entry.get("id"), previous.get("id")],
                        })
                        break
                seen.append(entry)

            sev_order = {"high": 0, "medium": 1, "low": 2}
            anomalies.sort(
                key=lambda anomaly: (
                    sev_order.get(anomaly["severity"], 9),
                    -float(anomaly.get("z_score") or anomaly.get("amount") or 0),
                )
            )

            seen_ids: set[int] = set()
            unique: list[dict] = []
            for anomaly in anomalies:
                ids = [entry_id for entry_id in (anomaly.get("entry_ids") or []) if entry_id]
                if ids:
                    key = frozenset(ids)
                    if key in seen_ids:
                        continue
                    seen_ids.update(ids)
                unique.append(anomaly)

            payload = {
                "month": current_month,
                "total": len(unique),
                "anomalies": unique[:20],
                "generated_at": now.isoformat(),
            }
            cache.set(cache_key, payload, 180)
            return jsonify(payload)
        except Exception as ex:
            logger.exception("anomalies error")
            return jsonify({"error": str(ex)}), 500

    @app.post("/api/finance/anomalies/<int:entry_id>/dismiss")
    @require_finance_key
    @limiter.limit("30/minute")
    def finance_anomaly_dismiss(entry_id: int):
        """Mark an anomaly as reviewed (adds a tag to the cashflow entry)."""
        try:
            entry = repo.get_fin_cashflow_entry(entry_id)
            if not entry:
                return jsonify({"error": "Lançamento não encontrado"}), 404
            existing_tags = str(entry.get("tags") or "")
            tags_list = [tag.strip() for tag in existing_tags.split(",") if tag.strip()]
            if "anomalia-revisada" not in tags_list:
                tags_list.append("anomalia-revisada")
            repo.update_fin_cashflow_entry(entry_id, {"tags": ", ".join(tags_list)})
            cache.delete("finance:anomalies")
            return jsonify({"status": "dismissed"})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500