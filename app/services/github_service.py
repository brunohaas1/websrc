from __future__ import annotations

from datetime import datetime, timezone

from ..utils import fetch_json
from .base import BaseCollector


class GitHubTrendCollector(BaseCollector):
    def run(self) -> int:
        items: list[dict] = []
        url = (
            "https://api.github.com/search/repositories"
            "?q=stars:%3E20000&sort=updated&order=desc&per_page=20"
        )

        try:
            payload = fetch_json(url)
            for repo in payload.get("items", []):
                items.append(
                    {
                        "item_type": "tech_ai",
                        "source": "GitHub",
                        "title": repo.get("full_name", "repo"),
                        "url": repo.get("html_url", "https://github.com"),
                        "summary": (
                            repo.get("description")
                            or "Repositório popular atualizado."
                        ),
                        "image_url": None,
                        "published_at": datetime.now(timezone.utc).isoformat(),
                        "extra": {
                            "stars": repo.get("stargazers_count"),
                            "language": repo.get("language"),
                        },
                    }
                )
        except Exception as exc:
            self.logger.warning("Falha ao coletar tendências GitHub: %s", exc)

        return self.save_items(items)
