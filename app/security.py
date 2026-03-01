from __future__ import annotations

import html
import re
from urllib.parse import urlparse


def sanitize_text(value: str, max_len: int = 250) -> str:
    text = html.escape((value or "").strip())
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def sanitize_optional_selector(value: str | None) -> str | None:
    if not value:
        return None
    selector = value.strip()
    if len(selector) > 120:
        return selector[:120]
    return selector


def is_safe_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False
