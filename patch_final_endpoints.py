#!/usr/bin/env python3
# Add inline editing PATCH endpoint and PDF report endpoint

with open('app/finance_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the last route and add new ones
new_routes = '''
    # Inline editing endpoint
    @app.patch("/api/finance/cashflow/<int:entry_id>")
    @require_finance_key
    def finance_update_cashflow_inline(entry_id):
        """Update single field via inline editing."""
        data = request.get_json() or {}
        allowed_fields = ["category", "description", "amount"]
        updates = {k: v for k, v in data.items() if k in allowed_fields}
        
        if not updates:
            return jsonify({"error": "no updates"}), 400
        
        try:
            result = repo.update_fin_cashflow_entry(entry_id, updates)
            if result:
                return jsonify({"status": "ok"}), 200
            return jsonify({"error": "not found"}), 404
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500
    
    # PDF report endpoint
    @app.get("/api/finance/report/pdf")
    @limiter.limit("10/minute")
    def finance_report_pdf():
        """Generate PDF report for a given month."""
        month = sanitize_text(str(request.args.get("month", "")), 7).strip()
        include_charts = request.args.get("includeCharts", "false").lower() == "true"
        include_analytics = request.args.get("includeAnalytics", "false").lower() == "true"
        
        if not month or not re.match(r"^\\d{4}-\\d{2}$", month):
            return jsonify({"error": "month invalid"}), 400
        
        try:
            # For now, return a simple placeholder PDF
            # In production, use reportlab or similar
            from io import BytesIO
            
            pdf_buffer = BytesIO()
            pdf_buffer.write(b"%PDF-1.4\\n")  # Simple PDF header
            pdf_buffer.write(b"1 0 obj\\n<< /Type /Catalog /Pages 2 0 R >> endobj\\n")
            pdf_buffer.write(b"2 0 obj\\n<< /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\\n")
            pdf_buffer.write(b"3 0 obj\\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\\n")
            pdf_buffer.write(f"4 0 obj\\nBT /F1 12 Tf 50 750 Td (Relatório Financeiro {month}) Tj ET\\nendobj\\n".encode())
            pdf_buffer.write(b"xref\\n0 5\\n0000000000 65535 f\\n0000000009 00000 n\\n0000000085 00000 n\\n0000000174 00000 n\\n0000000278 00000 n\\ntrailer\\n<< /Size 5 /Root 1 0 R >> startxref\\n400\\n%%EOF")
            
            pdf_buffer.seek(0)
            return pdf_buffer.getvalue(), 200, {
                "Content-Type": "application/pdf",
                "Content-Disposition": f"attachment; filename=relatorio-{month}.pdf"
            }
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500
'''

# Find insertion point (before closing of routes)
if 'def finance_analytics():' in content:
    # Add after analytics route
    insert_pos = content.find('def finance_budget_check():')
    if insert_pos > 0:
        # Find end of finance_budget_check
        end_pos = content.find('\n    @app.', insert_pos + 1)
        if end_pos > 0:
            content = content[:end_pos] + new_routes + content[end_pos:]
        else:
            # End of file
            content += new_routes
        
        with open('app/finance_routes.py', 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("✓ Added PATCH and PDF endpoints")
    else:
        print("✗ Could not find insertion point")
else:
    print("✗ Could not find analytics route")

print("✓✓ finance_routes.py updated")
