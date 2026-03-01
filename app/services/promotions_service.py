from __future__ import annotations

from datetime import datetime, timezone

from ..utils import fetch_json
from .base import BaseCollector


class PromotionsCollector(BaseCollector):
    def _normalize_product_slug(self, value: str) -> str:
        slug = (value or "").strip().strip("/")
        if not slug:
            return ""

        slug = slug.replace("/home", "").strip("/")

        if slug.startswith("pt-BR/"):
            slug = slug.removeprefix("pt-BR/")

        if slug.startswith("p/"):
            slug = slug.removeprefix("p/")

        if "/" in slug:
            slug = slug.split("/")[-1]

        return slug

    def _to_epic_product_url(self, slug: str) -> str:
        normalized = self._normalize_product_slug(slug)
        if not normalized:
            return "https://store.epicgames.com/pt-BR/free-games"
        return f"https://store.epicgames.com/pt-BR/p/{normalized}"

    def run(self) -> int:
        url = (
            "https://store-site-backend-static.ak.epicgames.com/"
            "freeGamesPromotions?locale=pt-BR&country=BR&allowCountries=BR"
        )
        items: list[dict] = []
        try:
            payload = fetch_json(url)
            if not isinstance(payload, dict):
                return 0

            games = (
                payload.get("data", {})
                .get("Catalog", {})
                .get("searchStore", {})
                .get("elements", [])
            )
            for game in games:
                promotions = game.get("promotions") or {}
                promotional_offers = promotions.get("promotionalOffers") or []
                if not promotional_offers:
                    continue

                title = game.get("title")
                offer_mappings = game.get("offerMappings") or []
                page_slug = ""
                if offer_mappings:
                    page_slug = offer_mappings[0].get("pageSlug") or ""

                url_slug = game.get("urlSlug") or ""
                product_slug = game.get("productSlug") or ""

                slug_candidates = [
                    self._normalize_product_slug(page_slug),
                    self._normalize_product_slug(product_slug),
                    self._normalize_product_slug(url_slug),
                ]
                valid_slug = next(
                    (slug for slug in slug_candidates if slug),
                    "",
                )
                game_url = self._to_epic_product_url(valid_slug)
                image = None
                for image_obj in game.get("keyImages", []):
                    if image_obj.get("url"):
                        image = image_obj["url"]
                        break

                items.append(
                    {
                        "item_type": "promotion",
                        "source": "Epic Games Store",
                        "title": title,
                        "url": game_url,
                        "summary": "Jogo com promoção ativa/grátis na Epic.",
                        "image_url": image,
                        "published_at": datetime.now(timezone.utc).isoformat(),
                        "extra": {
                            "seller": game.get("seller", {}),
                            "slug_candidates": slug_candidates,
                        },
                    }
                )
        except Exception as exc:
            self.logger.warning("Falha no monitor de promoções: %s", exc)

        return self.save_items(items)
