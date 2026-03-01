from __future__ import annotations

from datetime import datetime, timezone

from ..sources import GITHUB_REPOS_TO_WATCH
from ..utils import fetch_json
from .base import BaseCollector


class ReleaseCollector(BaseCollector):
    def run(self) -> int:
        items: list[dict] = []
        for repo in GITHUB_REPOS_TO_WATCH:
            url = f"https://api.github.com/repos/{repo}/releases/latest"
            try:
                release = fetch_json(url)
                tag = release.get("tag_name", "(sem tag)")
                items.append(
                    {
                        "item_type": "release",
                        "source": repo,
                        "title": f"Nova release: {tag}",
                        "url": release.get(
                            "html_url",
                            f"https://github.com/{repo}",
                        ),
                        "summary": (
                            release.get("name")
                            or "Release mais recente detectada."
                        ),
                        "image_url": None,
                        "published_at": (
                            release.get("published_at")
                            or datetime.now(timezone.utc).isoformat()
                        ),
                        "extra": {"repo": repo, "tag": tag},
                    }
                )
            except Exception as exc:
                self.logger.warning("Falha em release de %s: %s", repo, exc)
        return self.save_items(items)
