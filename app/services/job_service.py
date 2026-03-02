from __future__ import annotations

import feedparser
from dateutil import parser as date_parser

from .rss_service import RSSCollector


BRAZIL_TERMS = (
    "brasil",
    "brazil",
    "são paulo",
    "rio de janeiro",
    "curitiba",
    "porto alegre",
    "belo horizonte",
    "recife",
    "fortaleza",
    "florianópolis",
)

LATAM_TERMS = (
    "latam",
    "latin america",
    "south america",
)


class JobCollector(RSSCollector):
    def run(self) -> int:
        all_brazil_items: list[dict] = []
        fallback_items: list[dict] = []

        def to_item(feed: dict, entry, published: str | None, summary: str):
            return {
                "item_type": self.item_type,
                "source": feed["source"],
                "title": getattr(entry, "title", "(sem título)"),
                "url": getattr(entry, "link", ""),
                "summary": summary,
                "image_url": None,
                "published_at": published,
                "extra": {
                    "location": getattr(entry, "location", "")
                    or "Remote"
                },
            }

        for feed in self.feeds:
            try:
                parsed = feedparser.parse(feed["url"])
                for entry in parsed.entries[:40]:
                    title = getattr(entry, "title", "(sem título)")
                    summary = self._build_summary(entry, title)
                    location = getattr(entry, "location", "")

                    haystack = f"{title} {summary} {location}".lower()
                    has_brazil_match = any(
                        term in haystack for term in BRAZIL_TERMS
                    )
                    has_latam_match = any(
                        term in haystack for term in LATAM_TERMS
                    )

                    published = None
                    if getattr(entry, "published", None):
                        published_raw = getattr(entry, "published", "")
                        if (
                            published_raw
                            and not isinstance(published_raw, list)
                        ):
                            published_text = str(published_raw)
                            published = date_parser.parse(
                                published_text,
                            ).isoformat()

                    item = to_item(feed, entry, published, summary)

                    if has_brazil_match or has_latam_match:
                        all_brazil_items.append(item)
                    else:
                        fallback_items.append(item)
            except Exception as exc:
                self.logger.warning(
                    "Falha ao processar vagas %s: %s",
                    feed["url"],
                    exc,
                )

        if all_brazil_items:
            return self.save_items(all_brazil_items)

        for item in fallback_items[:20]:
            item["source"] = f"{item['source']} (fallback remoto)"
            item["summary"] = (
                "Sem vagas BR/LATAM no ciclo. "
                "Exibindo vagas remotas recentes. "
                f"{item['summary']}"
            )

        return self.save_items(fallback_items[:20])
