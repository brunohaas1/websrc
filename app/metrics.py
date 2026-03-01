from __future__ import annotations

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

HTTP_REQUESTS_TOTAL = Counter(
    "dashboard_http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "dashboard_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)


def mark_start() -> float:
    return time.perf_counter()


def observe_request(
    method: str,
    route: str,
    status_code: int,
    started_at: float,
) -> None:
    elapsed = max(0.0, time.perf_counter() - started_at)
    HTTP_REQUESTS_TOTAL.labels(
        method=method,
        route=route,
        status=str(status_code),
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(
        method=method,
        route=route,
    ).observe(elapsed)


def export_metrics() -> tuple[bytes, int, dict[str, str]]:
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
