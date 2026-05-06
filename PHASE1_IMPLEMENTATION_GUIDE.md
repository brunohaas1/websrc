# Finance Routes Modularization - Phase 1 Implementation Guide

## Quick Summary

The cashflow domain (`~3700 lines` from `app/finance_routes.py`) is being extracted into a separate, modular blueprint at `app/finance_blueprints/cashflow.py`.

**Status**: 8/20 routes implemented as example. Full rollout pending.

---

## How to Complete Phase 1

### Step 1: Copy Remaining Cashflow Routes

Copy these remaining routes from `app/finance_routes.py` to `app/finance_blueprints/cashflow.py`:

1. **Saved Filters** (`/api/finance/cashflow/saved-filters*`):
   - GET `/api/finance/cashflow/saved-filters` (list)
   - POST `/api/finance/cashflow/saved-filters` (add)
   - DELETE `/api/finance/cashflow/saved-filters/<id>` (delete)
   - PUT `/api/finance/cashflow/saved-filters/<id>/favorite` (toggle)
   - POST `/api/finance/cashflow/saved-filters/<id>/apply` (apply)
   - GET `/api/finance/cashflow/filters/templates` (templates)

2. **Summary & Alerts** (`/api/finance/cashflow/{summary,alerts,data-quality}`):
   - GET `/api/finance/cashflow/summary` (monthly summary)
   - GET `/api/finance/cashflow/alerts` (due alerts)
   - GET `/api/finance/cashflow/data-quality` (quality scoring)

3. **Advanced Analytics**:
   - GET `/api/finance/cashflow/kpis` (KPIs: savings rate, burn rate, runway)
   - POST `/api/finance/cashflow/scenario` (scenario simulation)

4. **OCR & Receipt Processing** (~1000 lines - most complex):
   - POST `/api/finance/cashflow/ocr` (OCR scan + field extraction)
   - GET `/api/finance/cashflow/ocr/history` (scan history)
   - Include all OCR helper functions

5. **Import/Reconciliation**:
   - POST `/api/finance/cashflow/import` (CSV/OFX import with async job queue)
   - GET `/api/finance/cashflow/import/jobs/<id>` (job status)
   - POST `/api/finance/cashflow/reconcile-auto` (auto-reconciliation)
   - POST `/api/finance/cashflow/reconcile-auto/confirm` (confirm reconciliation)

6. **Recurring Transactions**:
   - GET `/api/finance/cashflow/recurring` (list templates)
   - POST `/api/finance/cashflow/recurring` (add template)
   - PUT `/api/finance/cashflow/recurring/<id>` (update template)
   - DELETE `/api/finance/cashflow/recurring/<id>` (delete template)
   - POST `/api/finance/cashflow/recurring/run` (execute for month)

7. **Bulk Operations**:
   - POST `/api/finance/cashflow/bulk` (bulk update/delete)
   - GET `/api/finance/cashflow/bulk/dedup-stats` (dedup cache stats)

8. **Attachments**:
   - GET `/api/finance/cashflow/<id>/attachments` (list)
   - POST `/api/finance/cashflow/<id>/attachments` (upload)
   - DELETE `/api/finance/cashflow/attachments/<id>` (delete)

9. **Monthly Planning & Reports**:
   - GET `/api/finance/cashflow/month-plan` (week-level breakdown)
   - GET `/api/finance/cashflow/closing-pdf` (monthly closing PDF)
   - GET `/api/finance/cashflow/export-csv` (export as CSV)

10. **Classification & Rules**:
    - GET `/api/finance/cashflow/classify-rules` (list rules)
    - PUT `/api/finance/cashflow/classify-rules` (update rules)
    - POST `/api/finance/cashflow/auto-classify` (auto-classify entries)

11. **CRUD Operations**:
    - PUT `/api/finance/cashflow/<id>` (update entry)
    - DELETE `/api/finance/cashflow/<id>` (delete entry)
    - PUT `/api/finance/cashflow/<id>/status` (change payment status)
    - PATCH `/api/finance/cashflow/<id>` (inline edit)

12. **Rollover**:
    - POST `/api/finance/cashflow/rollover` (rollover entries to next month)

### Step 2: Extract Helper Functions

Create `app/finance_blueprints/cashflow_helpers.py` with these functions:

```python
# OCR Functions
_extract_text_from_receipt_image()
_extract_receipt_date()
_extract_receipt_amount()
_extract_receipt_merchant()
_score_ocr_candidate()
_normalize_ocr_text()
_normalize_ocr_errors_ptbr()
_detect_receipt_type()
_extract_cnpj()
_lookup_cnpj_data()
_lookup_cnpj_name()
_extract_payment_method()
_extract_receipt_items()
_pdf_bytes_to_image_bytes()
_pdf_bytes_to_all_images()
_compute_field_confidence()

# Classification Functions
_load_cashflow_classify_rules()
_infer_cashflow_category_from_text()
_infer_cashflow_entry_type_from_text()
_cnae_to_category()

# Import Functions
_execute_cashflow_import()
_enqueue_cashflow_import_job()
_cleanup_cashflow_import_jobs()

# Reconciliation
_build_reconcile_suggestions()
_cleanup_cashflow_review_cache()
_cleanup_ocr_cache()

# Constants
FINANCE_CACHE_TTLS
_OCR_PTBR_FIXES
_CNAE_CATEGORY_MAP
_COL_MAP
CASHFLOW_IMPORT_ASYNC_ROW_THRESHOLD
```

### Step 3: Update `app/finance_routes.py`

Replace the section `register_finance_routes()` to call the new blueprint:

```python
def register_finance_routes(app: Flask, limiter: Limiter) -> None:
    """Register all finance routes."""
    repo = Repository()
    cache = get_cache()
    logger_obj = logging.getLogger(__name__)
    
    # Prepare shared helpers dictionary
    _helpers = {
        '_audit': _audit,
        '_invalidate_cashflow_cache': _invalidate_cashflow_cache,
        '_as_float': _as_float,
        '_is_finite_number': _is_finite_number,
        'FINANCE_CACHE_TTLS': FINANCE_CACHE_TTLS,
        # ... other helpers
    }
    
    # Import and register domain blueprints
    from .finance_blueprints.cashflow import register_cashflow_routes
    register_cashflow_routes(app, limiter, repo, cache, logger_obj, _helpers)
    
    # Keep other domain routes in main module for now
    # (can extract in Phase 2, 3, 4)
```

### Step 4: Test & Validate

```bash
cd c:\Users\Bruno\websrc

# Run cashflow-specific tests
pytest tests/test_finance.py -k cashflow -v

# Run all finance tests
pytest tests/test_finance.py --tb=short

# Expected: 170 passing tests
```

### Step 5: Clean Up

1. Remove extracted code from `app/finance_routes.py`
2. Commit: `git commit -m "refactor(finance): phase 1 - extract cashflow into blueprint"`
3. Update line count: `wc -l app/finance_routes.py`

---

## File Layout After Phase 1

```
app/
├── finance_routes.py (7855 → ~4100 lines)
│   ├── Remaining: Assets, Transactions, Watchlist, Debts, Security
│   └── Shared helpers used by all blueprints
├── finance_blueprints/
│   ├── __init__.py
│   ├── cashflow.py (~3700 lines)
│   └── cashflow_helpers.py (~1500 lines)
├── finance_helpers.py (shared)
├── cache.py
├── repository.py
├── security.py
└── ...
```

---

## Key Patterns to Follow

### 1. Dependency Injection
All functions receive dependencies as parameters:
```python
def register_cashflow_routes(app, limiter, repo, cache, logger_obj, helpers):
    # Access helpers via: helpers.get('_audit')
```

### 2. URL Compatibility
**URLs must NOT change**. Only internal structure changes.
```python
@app.get("/api/finance/cashflow")  # Same URL as before
```

### 3. Error Handling
Keep same error format as original:
```python
return jsonify({"error": "message"}), 400
```

### 4. Caching & Invalidation
Use cache consistently:
```python
cache_key = f"finance:cashflow-{month}"
cached = cache.get(cache_key)
if cached is not None:
    return jsonify(cached)
# ... compute and cache
```

### 5. Audit Logging
Call audit helper for all mutations:
```python
_audit("add", "cashflow", entry_id, {"fields": data})
```

---

## Common Pitfalls to Avoid

1. ❌ Don't change URL paths (backward compatibility!)
2. ❌ Don't forget to inject helpers through the dict
3. ❌ Don't remove shared functions; keep them accessible
4. ❌ Don't forget `_invalidate_cashflow_cache()` after mutations
5. ❌ Don't skip `@require_finance_key` on write operations

---

## Verification Checklist

- [ ] All 20+ cashflow routes extracted
- [ ] All helper functions available via `helpers` dict
- [ ] No URL changes
- [ ] All validation logic preserved
- [ ] Cache invalidation still works
- [ ] Audit logging in place
- [ ] 170 tests passing
- [ ] No TypeErrors or AttributeErrors

---

## Next: Phase 2 (After Phase 1 Complete)

Once Phase 1 is done and all tests pass:
- Extract Watchlist blueprint (~400 lines)
- Extract Assets/Transactions blueprint (~500 lines)
- Extract Security blueprint (~300 lines)

Same pattern applies to all phases.

