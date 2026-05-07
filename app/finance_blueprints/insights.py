"""Finance insights routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def register_insights_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    if helpers is None:
        helpers = {}

    _fmt_brl = helpers.get("_fmt_brl", lambda value: str(value))

    from flask import jsonify

    @app.get("/api/finance/insights")
    @limiter.limit("20/minute")
    def finance_insights():
        cache_key = "finance:insights"
        cached = cache.get(cache_key)
        if cached:
            return jsonify(cached)
        try:
            now = datetime.now(timezone.utc)
            current_month = now.strftime("%Y-%m")
            prev_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

            analytics_cur = repo.get_fin_cashflow_analytics(month=current_month)
            analytics_prev = repo.get_fin_cashflow_analytics(month=prev_month)
            debts = repo.list_fin_debts(status="open")
            goals = [goal for goal in repo.list_fin_goals() if goal.get("status") != "completed"]
            budget_rows = (analytics_cur.get("budget") or {}).get("items") or []

            cur_totals = analytics_cur.get("totals") or {}
            prev_totals = analytics_prev.get("totals") or {}
            insights: list[dict] = []

            income = float(cur_totals.get("income") or 0)
            expense = float(cur_totals.get("expense") or 0)
            balance = income - expense
            savings_rate = (balance / income * 100) if income > 0 else 0

            if income > 0:
                if savings_rate >= 20:
                    insights.append({
                        "icon": "🟢", "type": "positive",
                        "title": "Ótima taxa de poupança",
                        "body": f"Você poupou {savings_rate:.1f}% da sua renda em {current_month} — acima do recomendado (20%). Continue assim!",
                    })
                elif savings_rate >= 10:
                    insights.append({
                        "icon": "🟡", "type": "neutral",
                        "title": "Poupança adequada",
                        "body": f"Sua taxa de poupança foi de {savings_rate:.1f}% em {current_month}. Tente chegar a 20% para acelerar seus objetivos.",
                    })
                elif savings_rate > 0:
                    insights.append({
                        "icon": "🔴", "type": "warning",
                        "title": "Taxa de poupança baixa",
                        "body": f"Você poupou apenas {savings_rate:.1f}% da sua renda em {current_month}. Analise onde reduzir gastos.",
                    })
                else:
                    insights.append({
                        "icon": "🚨", "type": "danger",
                        "title": "Déficit no mês",
                        "body": f"Seus gastos ({_fmt_brl(expense)}) superaram a renda ({_fmt_brl(income)}) em {current_month}. Atenção ao orçamento!",
                    })

            exp_prev = float(prev_totals.get("expense") or 0)
            if exp_prev > 0 and expense > 0:
                pct_change = (expense - exp_prev) / exp_prev * 100
                if pct_change > 15:
                    insights.append({
                        "icon": "📈", "type": "warning",
                        "title": f"Gastos +{pct_change:.1f}% vs mês anterior",
                        "body": f"Seus gastos aumentaram {pct_change:.1f}% em relação a {prev_month} ({_fmt_brl(exp_prev)} → {_fmt_brl(expense)}). Verifique as categorias.",
                    })
                elif pct_change < -10:
                    insights.append({
                        "icon": "📉", "type": "positive",
                        "title": f"Gastos -{abs(pct_change):.1f}% vs mês anterior",
                        "body": f"Ótimo! Você reduziu gastos em {abs(pct_change):.1f}% em relação a {prev_month}. Economia de {_fmt_brl(abs(expense - exp_prev))}.",
                    })

            exp_cats_list = analytics_cur.get("top_expenses") or []
            if exp_cats_list and income > 0:
                top = exp_cats_list[0]
                top_cat = top.get("category", "")
                top_val = float(top.get("amount") or 0)
                if (top_val / income) > 0.30:
                    insights.append({
                        "icon": "💡", "type": "tip",
                        "title": f"Categoria dominante: {top_cat}",
                        "body": f"'{top_cat}' representa {top_val / income * 100:.1f}% da sua renda ({_fmt_brl(top_val)}). Considere se há espaço para redução.",
                    })

            overruns = [
                row for row in budget_rows
                if float(row.get("limit") or 0) > 0 and float(row.get("spent") or 0) > float(row.get("limit") or 0)
            ]
            if overruns:
                names = ", ".join(row["category"] for row in overruns[:3])
                insights.append({
                    "icon": "⚠️", "type": "warning",
                    "title": f"{len(overruns)} categoria(s) acima do orçamento",
                    "body": f"Categorias que ultrapassaram o limite: {names}. Revise seu orçamento ou reduza os gastos.",
                })

            if debts:
                total_debt = sum(float(debt.get("current_balance") or 0) for debt in debts)
                total_payment = sum(float(debt.get("monthly_payment") or 0) for debt in debts)
                debt_pct = (total_payment / income * 100) if income > 0 else 0
                if debt_pct > 30:
                    insights.append({
                        "icon": "💳", "type": "danger",
                        "title": "Comprometimento alto com dívidas",
                        "body": f"{debt_pct:.1f}% da sua renda vai para parcelas ({_fmt_brl(total_payment)}/mês). O ideal é até 30%. Saldo devedor total: {_fmt_brl(total_debt)}.",
                    })
                elif debt_pct > 0:
                    insights.append({
                        "icon": "💳", "type": "neutral",
                        "title": "Dívidas sob controle",
                        "body": f"Você compromete {debt_pct:.1f}% da renda com parcelas ({_fmt_brl(total_payment)}/mês). Saldo devedor: {_fmt_brl(total_debt)}.",
                    })

            near_goals = [
                goal for goal in goals
                if float(goal.get("target_amount") or 0) > 0
                and (float(goal.get("current_amount") or 0) / float(goal["target_amount"])) >= 0.80
            ]
            if near_goals:
                goal = near_goals[0]
                pct = float(goal["current_amount"]) / float(goal["target_amount"]) * 100
                insights.append({
                    "icon": "🎯", "type": "positive",
                    "title": f"Meta '{goal['name']}' quase lá!",
                    "body": f"Você está a {pct:.0f}% da sua meta '{goal['name']}' ({_fmt_brl(goal['current_amount'])} / {_fmt_brl(goal['target_amount'])}). Continue assim!",
                })

            if income > 0 and balance > 0 and not near_goals:
                monthly_expenses = expense
                if monthly_expenses > 0 and balance < monthly_expenses * 0.5:
                    insights.append({
                        "icon": "🛡️", "type": "tip",
                        "title": "Reforce sua reserva de emergência",
                        "body": f"Com gastos de {_fmt_brl(monthly_expenses)}/mês, sua reserva ideal é {_fmt_brl(monthly_expenses * 6)}. Tente poupar pelo menos {_fmt_brl(monthly_expenses * 0.1)}/mês para isso.",
                    })

            if not insights:
                insights.append({
                    "icon": "📊", "type": "neutral",
                    "title": "Sem dados suficientes",
                    "body": "Registre mais lançamentos para receber insights personalizados sobre suas finanças.",
                })

            payload = {"month": current_month, "insights": insights, "generated_at": now.isoformat()}
            cache.set(cache_key, payload, 300)
            return jsonify(payload)
        except Exception as ex:
            logger.exception("insights error")
            return jsonify({"error": str(ex)}), 500