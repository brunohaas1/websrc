from __future__ import annotations

import feedparser
from dateutil import parser as date_parser

from .base import BaseCollector


class RSSCollector(BaseCollector):
    def __init__(self, app, repo, feeds: list[dict], item_type: str):
        super().__init__(app, repo)
        self.feeds = feeds
        self.item_type = item_type

    def run(self) -> int:
        feed_entry_limit = int(self.app.config.get("FEED_ENTRY_LIMIT", 30))
        all_items: list[dict] = []
        for feed in self.feeds:
            try:
                parsed = feedparser.parse(feed["url"])
                for entry in parsed.entries[:feed_entry_limit]:
                    published = None
                    if getattr(entry, "published", None):
                        published_raw = getattr(entry, "published", "")
                        if (
                            published_raw
                            and not isinstance(published_raw, list)
                        ):
                            published = date_parser.parse(
                                str(published_raw),
                            ).isoformat()

                    image_url = None
                    media_thumbnail = getattr(entry, "media_thumbnail", [])
                    if media_thumbnail:
                        image_url = media_thumbnail[0].get("url")

                    if not image_url:
                        media_content = getattr(entry, "media_content", [])
                        if media_content:
                            candidate = media_content[0].get("url")
                            if candidate and candidate.startswith("http"):
                                image_url = candidate

                    all_items.append(
                        {
                            "item_type": self.item_type,
                            "source": feed["source"],
                            "title": getattr(entry, "title", "(sem título)"),
                            "url": getattr(entry, "link", ""),
                            "summary": getattr(entry, "summary", ""),
                            "image_url": image_url,
                            "published_at": published,
                            "extra": {},
                        }
                    )
            except Exception as exc:
                self.logger.warning(
                    "Falha ao processar feed %s: %s",
                    feed["url"],
                    exc,
                )
        return self.save_items(all_items)
