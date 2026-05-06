#!/usr/bin/env python3
# Patch script to add advanced filters to repository

with open('app/repository.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Update method signature
old_sig = '''    def list_fin_cashflow_entries(
        self,
        month: str | None = None,
        entry_type: str | None = None,
        payment_status: str | None = None,
        q: str | None = None,
        cost_center: str | None = None,
        subcategory: str | None = None,
        tag: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:'''

new_sig = '''    def list_fin_cashflow_entries(
        self,
        month: str | None = None,
        entry_type: str | None = None,
        payment_status: str | None = None,
        q: str | None = None,
        cost_center: str | None = None,
        subcategory: str | None = None,
        tag: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        category: str | None = None,
        credit_card_id: int | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:'''

if old_sig in content:
    content = content.replace(old_sig, new_sig)
    print('✓ Updated method signature')
else:
    print('✗ Could not find method signature')

# Add filters before first ORDER BY
old_block = '''            q_like = f"%{str(q).lower()}%"
            params.extend([q_like, q_like, q_like, q_like, q_like, q_like])

        query += " ORDER BY e.entry_date DESC, e.created_at DESC LIMIT ?"'''

new_block = '''            q_like = f"%{str(q).lower()}%"
            params.extend([q_like, q_like, q_like, q_like, q_like, q_like])

        if date_from:
            query += " AND e.entry_date >= ?"
            params.append(date_from)

        if date_to:
            query += " AND e.entry_date <= ?"
            params.append(date_to)

        if category:
            query += " AND LOWER(COALESCE(e.category, '')) = LOWER(?)"
            params.append(category)

        if credit_card_id:
            query += " AND e.credit_card_id = ?"
            params.append(int(credit_card_id))

        if amount_min is not None:
            query += " AND e.amount >= ?"
            params.append(float(amount_min))

        if amount_max is not None:
            query += " AND e.amount <= ?"
            params.append(float(amount_max))

        query += " ORDER BY e.entry_date DESC, e.created_at DESC LIMIT ?"'''

if old_block in content:
    content = content.replace(old_block, new_block, 1)
    print('✓ Added main query filters')
else:
    print('✗ Could not find ORDER BY block in main query')

# Add filters before second ORDER BY (fallback query)
old_fallback = '''            q_like = f"%{str(q).lower()}%"
            fallback_params.extend([q_like, q_like, q_like, q_like, q_like, q_like])

        fallback_query += " ORDER BY e.entry_date DESC, e.created_at DESC LIMIT ?"'''

new_fallback = '''            q_like = f"%{str(q).lower()}%"
            fallback_params.extend([q_like, q_like, q_like, q_like, q_like, q_like])

        if date_from:
            fallback_query += " AND e.entry_date >= ?"
            fallback_params.append(date_from)

        if date_to:
            fallback_query += " AND e.entry_date <= ?"
            fallback_params.append(date_to)

        if category:
            fallback_query += " AND LOWER(COALESCE(e.category, '')) = LOWER(?)"
            fallback_params.append(category)

        if credit_card_id:
            fallback_query += " AND e.credit_card_id = ?"
            fallback_params.append(int(credit_card_id))

        if amount_min is not None:
            fallback_query += " AND e.amount >= ?"
            fallback_params.append(float(amount_min))

        if amount_max is not None:
            fallback_query += " AND e.amount <= ?"
            fallback_params.append(float(amount_max))

        fallback_query += " ORDER BY e.entry_date DESC, e.created_at DESC LIMIT ?"'''

if old_fallback in content:
    content = content.replace(old_fallback, new_fallback)
    print('✓ Added fallback query filters')
else:
    print('✗ Could not find ORDER BY block in fallback query')

with open('app/repository.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✓✓✓ repository.py updated successfully')
