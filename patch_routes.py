#!/usr/bin/env python3
# Update finance_routes.py to accept advanced filters

with open('app/finance_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and update the finance_list_cashflow function to accept new params
old_func = '''    @app.get("/api/finance/cashflow")
    @limiter.limit("30/minute")
    def finance_list_cashflow():
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        entry_type = sanitize_text(str(request.args.get("type", "")), 12).strip().lower()
        payment_status = sanitize_text(str(request.args.get("status", "")), 12).strip().lower()
        cost_center = sanitize_text(str(request.args.get("cost_center", "")), 60).strip()
        subcategory = sanitize_text(str(request.args.get("subcategory", "")), 60).strip()
        tag = sanitize_text(str(request.args.get("tag", "")), 30).strip().lower()
        q = sanitize_text(str(request.args.get("q", "")), 120).strip()
        limit = int(request.args.get("limit", "500"))

        if month and not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400
        if entry_type and entry_type not in ("income", "expense"):
            return jsonify({"error": "type inválido (income|expense)"}), 400
        if payment_status and payment_status not in ("pending", "paid"):
            return jsonify({"error": "status inválido (pending|paid)"}), 400

        payload = repo.list_fin_cashflow_entries(
            month=month or None,
            entry_type=entry_type or None,
            payment_status=payment_status or None,
            q=q or None,
            cost_center=cost_center or None,
            subcategory=subcategory or None,
            tag=tag or None,
            limit=max(1, min(2000, limit)),
        )
        return jsonify(payload)'''

new_func = '''    @app.get("/api/finance/cashflow")
    @limiter.limit("30/minute")
    def finance_list_cashflow():
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        entry_type = sanitize_text(str(request.args.get("type", "")), 12).strip().lower()
        payment_status = sanitize_text(str(request.args.get("status", "")), 12).strip().lower()
        cost_center = sanitize_text(str(request.args.get("cost_center", "")), 60).strip()
        subcategory = sanitize_text(str(request.args.get("subcategory", "")), 60).strip()
        category = sanitize_text(str(request.args.get("category", "")), 60).strip()
        tag = sanitize_text(str(request.args.get("tag", "")), 30).strip().lower()
        q = sanitize_text(str(request.args.get("q", "")), 120).strip()
        date_from = sanitize_text(str(request.args.get("date_from", "")), 10).strip()
        date_to = sanitize_text(str(request.args.get("date_to", "")), 10).strip()
        credit_card_id = request.args.get("credit_card_id", "")
        amount_min = request.args.get("amount_min", "")
        amount_max = request.args.get("amount_max", "")
        limit = int(request.args.get("limit", "500"))

        if month and not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month inválido (use YYYY-MM)"}), 400
        if entry_type and entry_type not in ("income", "expense"):
            return jsonify({"error": "type inválido (income|expense)"}), 400
        if payment_status and payment_status not in ("pending", "paid"):
            return jsonify({"error": "status inválido (pending|paid)"}), 400
        if date_from and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_from):
            return jsonify({"error": "date_from inválido (use YYYY-MM-DD)"}), 400
        if date_to and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_to):
            return jsonify({"error": "date_to inválido (use YYYY-MM-DD)"}), 400

        try:
            cid = int(credit_card_id) if credit_card_id else None
        except (ValueError, TypeError):
            cid = None

        try:
            amin = float(amount_min) if amount_min else None
        except (ValueError, TypeError):
            amin = None

        try:
            amax = float(amount_max) if amount_max else None
        except (ValueError, TypeError):
            amax = None

        payload = repo.list_fin_cashflow_entries(
            month=month or None,
            entry_type=entry_type or None,
            payment_status=payment_status or None,
            q=q or None,
            cost_center=cost_center or None,
            subcategory=subcategory or None,
            category=category or None,
            tag=tag or None,
            date_from=date_from or None,
            date_to=date_to or None,
            credit_card_id=cid,
            amount_min=amin,
            amount_max=amax,
            limit=max(1, min(2000, limit)),
        )
        return jsonify(payload)'''

if old_func in content:
    content = content.replace(old_func, new_func)
    print('✓ Updated finance_list_cashflow route')
else:
    print('✗ Could not find finance_list_cashflow function')

with open('app/finance_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✓✓ finance_routes.py updated')
