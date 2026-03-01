import hashlib
import json
import logging
import re
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .logging_setup import configure_json_logging


logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO", log_json: bool = False) -> None:
    if log_json:
        configure_json_logging(level)
        return

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def to_dedup_key(item_type: str, source: str, url: str, title: str) -> str:
    raw = f"{item_type}|{source}|{url}|{title}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def can_fetch_url(url: str, user_agent: str = "*") -> bool:
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception as exc:
        logger.warning("Falha ao validar robots.txt para %s: %s", url, exc)
        return False


def extract_price(text: str) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d,\.]", "", text)
    if not cleaned:
        return None

    if cleaned.count(",") == 1 and cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(",") == 1 and cleaned.count(".") == 0:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1 and cleaned.count(",") == 0:
        cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_json(url: str, timeout: int = 20) -> dict | list:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "PersonalDashboardBot/1.0"},
    )
    response.raise_for_status()
    return response.json()


def fetch_text(url: str, timeout: int = 20) -> str:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "PersonalDashboardBot/1.0"},
    )
    response.raise_for_status()
    return response.text
