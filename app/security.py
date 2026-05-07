from __future__ import annotations

import functools
import hmac
import html
import logging
import re
from urllib.parse import urlparse

from flask import current_app, jsonify, request


def sanitize_text(value: str, max_len: int = 250) -> str:
    text = html.escape((value or "").strip())
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def sanitize_optional_selector(value: str | None) -> str | None:
    if not value:
        return None
    selector = value.strip()[:120]
    if not selector:
        return None
    # Only allow safe CSS selector characters
    if not re.match(
        r'^[a-zA-Z0-9_\-\.#\[\]=\'"~:>+, *^$|()@]+$',
        selector,
    ):
        return None
    return selector


def is_safe_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def require_admin_key(fn):
    """Decorator: reject requests without a valid ADMIN_API_KEY."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        configured_key = current_app.config.get("ADMIN_API_KEY") or ""
        enforce_keys = bool(current_app.config.get("REQUIRE_API_KEYS", False)) and not (
            bool(current_app.testing) or bool(current_app.debug)
        )
        if not configured_key:
            if enforce_keys:
                logging.getLogger(__name__).error(
                    "ADMIN_API_KEY required but not configured",
                )
                return jsonify({"error": "Server not configured for admin auth"}), 503
            logging.getLogger(__name__).warning(
                "ADMIN_API_KEY not configured; admin endpoint open (dev mode)",
            )
            return fn(*args, **kwargs)

        provided = (
            request.headers.get("X-Admin-Key", "")
            or request.args.get("admin_key", "")
        )
        if not provided or not hmac.compare_digest(
            provided, configured_key,
        ):
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


def require_finance_key(fn):
    """Decorator: reject requests without a valid FINANCE_API_KEY.

    When FINANCE_API_KEY is empty/unset the endpoint is open only in dev mode.
    Accepts the key via ``X-Finance-Key`` header or ``finance_key`` query param.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        configured_key = current_app.config.get("FINANCE_API_KEY") or ""
        enforce_keys = bool(current_app.config.get("REQUIRE_API_KEYS", False)) and not (
            bool(current_app.testing) or bool(current_app.debug)
        )
        if not configured_key:
            if enforce_keys:
                logging.getLogger(__name__).error(
                    "FINANCE_API_KEY required but not configured",
                )
                return jsonify({"error": "Server not configured for finance auth"}), 503
            return fn(*args, **kwargs)

        provided = (
            request.headers.get("X-Finance-Key", "")
            or request.args.get("finance_key", "")
        )
        if not provided or not hmac.compare_digest(provided, configured_key):
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper
