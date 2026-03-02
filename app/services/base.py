import logging
from abc import ABC, abstractmethod

from .ai_enrichment_service import LocalAIEnricher


class BaseCollector(ABC):
    def __init__(self, app, repo):
        self.app = app
        self.repo = repo
        self.logger = logging.getLogger(self.__class__.__name__)
        self.ai_enricher = LocalAIEnricher(app)

    @abstractmethod
    def run(self) -> int:
        raise NotImplementedError

    def save_items(self, items: list[dict]) -> int:
        inserted = 0
        base_limit = int(
            self.app.config.get("AI_LOCAL_MAX_ENRICH_PER_RUN", 12),
        )

        enrich_flags = [
            self.ai_enricher.should_enrich(item) for item in items
        ]
        candidate_count = sum(1 for flag in enrich_flags if flag)
        adaptive_limit = self.ai_enricher.adaptive_limit(
            base_limit,
            candidate_count,
        )

        enriched_inserts = 0

        for item, is_candidate in zip(items, enrich_flags):
            if self.repo.item_exists(item):
                continue

            enriched_item = item
            should_enrich = is_candidate and enriched_inserts < adaptive_limit
            if should_enrich:
                enriched_item = self.ai_enricher.enrich_item(item)

            if self.repo.upsert_item(enriched_item):
                inserted += 1
                if should_enrich:
                    enriched_inserts += 1
        return inserted
