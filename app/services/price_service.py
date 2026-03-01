from __future__ import annotations

from bs4 import BeautifulSoup

from ..utils import can_fetch_url, extract_price, fetch_text
from .base import BaseCollector


class PriceCollector(BaseCollector):
    def run(self) -> int:
        watches = self.repo.list_price_watches()
        captured = 0

        for watch in watches:
            if not watch.get("active"):
                continue

            url = watch["product_url"]
            if not can_fetch_url(url):
                self.logger.info("robots.txt bloqueia coleta para %s", url)
                continue

            try:
                html = fetch_text(url)
                soup = BeautifulSoup(html, "html.parser")

                selector = watch.get("css_selector") or "body"
                node = soup.select_one(selector)
                if node is None:
                    self.logger.warning(
                        "Seletor não encontrado para watch %s",
                        watch["id"],
                    )
                    continue

                price = extract_price(node.get_text(" ", strip=True))
                if price is None:
                    self.logger.warning(
                        "Preço não identificado para watch %s",
                        watch["id"],
                    )
                    continue

                self.repo.record_price(watch["id"], price)
                captured += 1

                if price <= watch["target_price"]:
                    self.repo.create_alert(
                        alert_type="price_target",
                        title=f"Preço alvo atingido: {watch['name']}",
                        message=(
                            f"{watch['name']} chegou a"
                            f" {price:.2f} {watch['currency']}"
                        ),
                        payload={
                            "watch_id": watch["id"],
                            "price": price,
                            "url": watch["product_url"],
                        },
                    )
            except Exception as exc:
                self.logger.warning(
                    "Falha ao monitorar preço '%s': %s",
                    watch["name"],
                    exc,
                )

        return captured
