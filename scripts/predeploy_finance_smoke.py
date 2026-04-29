from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app


def main() -> int:
    app = create_app(start_scheduler=False)
    client = app.test_client()

    checks = [
        "/api/finance/cashflow?limit=20",
        "/api/finance/cashflow?limit=20&month=2026-04",
        "/api/finance/cashflow/analytics",
        "/api/finance/cashflow/analytics?month=2026-04",
        "/api/finance/cashflow/export-csv?month=2026-04",
        "/api/finance/cashflow/summary?month=2026-04",
        "/api/finance/cashflow/categories",
        "/api/finance/global-search?q=vale&limit=5",
    ]

    has_error = False
    for route in checks:
        res = client.get(route)
        status = int(res.status_code)
        print(f"{route} => {status}")
        if status >= 500:
            has_error = True

    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
