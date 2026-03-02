"""Service uptime monitor — checks health of personal services."""
from __future__ import annotations

import logging
import time

import requests

from ..repository import Repository


logger = logging.getLogger(__name__)


class ServiceMonitorChecker:
    """Periodically check configured service monitors and record status."""

    def __init__(self, app, repo: Repository):
        self.app = app
        self.repo = repo

    def run(self) -> int:
        monitors = self.repo.list_service_monitors()
        checked = 0

        for monitor in monitors:
            active = monitor.get("active")
            # Handle both SQLite (1/0) and Postgres (True/False)
            if active in (0, False, "0", None):
                continue

            monitor_id = int(monitor["id"])
            url = str(monitor.get("url", ""))
            method = str(monitor.get("check_method", "GET")).upper()
            expected_status = int(monitor.get("expected_status", 200))
            timeout = int(monitor.get("timeout_seconds", 5))

            status, latency_ms = self._check_service(
                url, method, expected_status, timeout,
            )
            self.repo.update_service_monitor_status(
                monitor_id, status, latency_ms,
            )
            checked += 1
            logger.debug(
                "Monitor %s (%s): %s (%.0f ms)",
                monitor.get("name"), url, status, latency_ms or 0,
            )

        return checked

    @staticmethod
    def _check_service(
        url: str,
        method: str,
        expected_status: int,
        timeout: int,
    ) -> tuple[str, float | None]:
        try:
            start = time.monotonic()
            resp = requests.request(
                method,
                url,
                timeout=timeout,
                allow_redirects=True,
                headers={"User-Agent": "DashboardServiceMonitor/1.0"},
            )
            elapsed_ms = (time.monotonic() - start) * 1000

            if resp.status_code == expected_status:
                return "up", round(elapsed_ms, 1)
            return f"unexpected:{resp.status_code}", round(elapsed_ms, 1)

        except requests.ConnectionError:
            return "down", None
        except requests.Timeout:
            return "timeout", None
        except Exception as exc:
            logger.warning("Monitor check error for %s: %s", url, exc)
            return "error", None
