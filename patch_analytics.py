#!/usr/bin/env python3
# Add analytics methods to repository.py

with open('app/repository.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find where to insert (before closing of class)
analytics_methods = '''
    def get_fin_analytics(self, month):
        """Get analytics and insights for a given month."""
        if not re.match(r"^\\d{4}-\\d{2}$", month):
            return {}
        
        query = self._sql("""
            SELECT 
                entry_type,
                category,
                SUM(CASE WHEN e.amount > 0 THEN e.amount ELSE 0 END) as amount,
                COUNT(*) as count
            FROM fin_cashflow_entries e
            WHERE strftime('%Y-%m', e.entry_date) = ?
            GROUP BY entry_type, category
            ORDER BY amount DESC
        """)
        
        conn = get_connection(self.database_target)
        cursor = conn.cursor()
        rows = cursor.execute(query, (month,)).fetchall()
        conn.close()
        
        categories = {"income": [], "expense": []}
        for row in rows:
            entry_type, category, amount, count = row
            if entry_type in ("income", "expense"):
                categories[entry_type].append({
                    "category": category,
                    "amount": float(amount) if amount else 0,
                    "count": int(count) if count else 0,
                })
        
        return {"categories": categories}
    
    def get_budget_alerts(self, month):
        """Get budget alerts for a given month."""
        if not re.match(r"^\\d{4}-\\d{2}$", month):
            return []
        
        query = self._sql("""
            SELECT 
                category,
                SUM(CASE WHEN e.amount > 0 THEN e.amount ELSE 0 END) as total
            FROM fin_cashflow_entries e
            WHERE strftime('%Y-%m', e.entry_date) = ?
                AND e.entry_type = 'expense'
            GROUP BY category
        """)
        
        conn = get_connection(self.database_target)
        cursor = conn.cursor()
        rows = cursor.execute(query, (month,)).fetchall()
        conn.close()
        
        alerts = []
        for row in rows:
            category, total = row
            # Default budgets (in a real app, these would be from settings)
            budget_limits = {
                "Food": 500,
                "Transport": 300,
                "Entertainment": 200,
            }
            limit = budget_limits.get(category, 0)
            if limit > 0 and total >= limit:
                alerts.append({
                    "category": category,
                    "spent": float(total) if total else 0,
                    "limit": limit,
                    "percentage": int((total / limit) * 100) if limit > 0 else 0,
                })
        
        return sorted(alerts, key=lambda x: x["percentage"], reverse=True)
'''

# Find the end of the Repository class (before last closing of methods)
if "class Repository:" in content:
    # Insert before the last method or before any closing
    lines = content.split("\n")
    insert_line = -2  # Default to near end
    
    for i in range(len(lines) - 1, 0, -1):
        if lines[i].strip().startswith("def ") and lines[i].startswith("    def "):
            # Found last method, insert after it
            insert_line = i
            # Find the end of this method
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("    def ") or (lines[j].strip() and not lines[j].startswith("        ")):
                    insert_line = j - 1
                    break
            break
    
    if insert_line > 0:
        lines.insert(insert_line + 1, analytics_methods)
        content = "\n".join(lines)
        
        with open('app/repository.py', 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("✓ Added analytics methods (get_fin_analytics, get_budget_alerts)")
    else:
        print("✗ Could not find insertion point")
else:
    print("✗ Could not find Repository class")

print("✓✓ repository.py updated")
