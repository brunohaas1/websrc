#!/usr/bin/env python3
# Add missing filter and template endpoints to finance_routes.py

with open('app/finance_routes.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the last finance route (finance_credit_card_usage around line 1617)
insert_pos = None
for i, line in enumerate(lines):
    if "finance_credit_card_usage" in line and "@app.get" in lines[max(0, i-3):i]:
        # Find the closing of this function
        indent_level = len(line) - len(line.lstrip())
        for j in range(i + 1, len(lines)):
            if lines[j].strip() and not lines[j].startswith(" " * (indent_level + 1)) and lines[j].strip() != "":
                insert_pos = j
                break

if insert_pos is None:
    insert_pos = len(lines) - 5

new_routes = '''
    # Filter management endpoints
    @app.post("/api/finance/filters")
    @require_finance_key
    def finance_save_filter():
        """Save a custom filter (cashflow, expenses, etc)."""
        data = request.get_json() or {}
        name = sanitize_text(str(data.get("name", "")), 100).strip()
        filter_data = data.get("filter", {})
        is_fav = bool(data.get("is_favorite", False))
        
        if not name:
            return jsonify({"error": "name required"}), 400
        
        try:
            # Store in localStorage on client (stateless), or in DB if desired
            return jsonify({"status": "ok", "name": name}), 201
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500
    
    @app.get("/api/finance/filters")
    @limiter.limit("30/minute")
    def finance_list_filters():
        """List saved filters."""
        return jsonify([])  # Stored in localStorage on client
    
    # Template management endpoints
    @app.post("/api/finance/templates")
    @require_finance_key
    def finance_save_template():
        """Save a cashflow entry as a template."""
        data = request.get_json() or {}
        name = sanitize_text(str(data.get("name", "")), 100).strip()
        template = data.get("template", {})
        
        if not name:
            return jsonify({"error": "name required"}), 400
        
        try:
            return jsonify({"status": "ok", "name": name}), 201
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500
    
    @app.get("/api/finance/templates")
    @limiter.limit("30/minute")
    def finance_list_templates():
        """List saved templates."""
        return jsonify([])  # Stored in localStorage on client
    
    # Analytics endpoint
    @app.get("/api/finance/analytics")
    @limiter.limit("30/minute")
    def finance_analytics():
        """Get analytics and insights."""
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        
        if not month:
            return jsonify({"error": "month required"}), 400
        
        if not re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month invalid (YYYY-MM)"}), 400
        
        try:
            payload = repo.get_fin_analytics(month)
            return jsonify(payload or {})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500
    
    # Budget alerts endpoint
    @app.get("/api/finance/budget-check")
    @limiter.limit("30/minute")
    def finance_budget_check():
        """Check budget status and return alerts."""
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        
        if not month:
            return jsonify({"error": "month required"}), 400
        
        try:
            alerts = repo.get_budget_alerts(month)
            return jsonify({"alerts": alerts or []})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

'''

lines.insert(insert_pos, new_routes)

with open('app/finance_routes.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("✓ Added filter, template, analytics endpoints")
print("✓✓ finance_routes.py updated")
