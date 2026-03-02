"""Currency exchange rate collector using AwesomeAPI."""
from __future__ import annotations

import logging

from ..repository import Repository
from ..utils import fetch_json


logger = logging.getLogger(__name__)


class CurrencyCollector:
    """Fetch USD/BRL, EUR/BRL, BTC/BRL from AwesomeAPI."""

    PAIR_MAP = {
        "USDBRL": "USD-BRL",
        "EURBRL": "EUR-BRL",
        "BTCBRL": "BTC-BRL",
    }

    def __init__(self, app, repo: Repository):
        self.app = app
        self.repo = repo
        self.api_url = app.config.get(
            "CURRENCY_API_URL",
            "https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL",
        )

    def run(self) -> int:
        try:
            data = fetch_json(self.api_url, timeout=10)
        except Exception as exc:
            logger.warning("Falha ao buscar câmbio: %s", exc)
            return 0

        updated = 0
        for api_key, pair_name in self.PAIR_MAP.items():
            entry = data.get(api_key)
            if not entry:
                continue
            try:
                rate = float(entry.get("bid", 0))
                variation = float(entry.get("pctChange", 0))
                self.repo.upsert_currency_rate(pair_name, rate, variation)
                updated += 1
            except (TypeError, ValueError) as exc:
                logger.warning("Erro ao processar %s: %s", pair_name, exc)

        return updated
