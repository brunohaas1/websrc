from __future__ import annotations

import logging

from ..repository import Repository
from ..sources import (
    AI_TECH_FEEDS,
    JOB_FEEDS,
    NEWS_FEEDS,
    YOUTUBE_CHANNEL_FEEDS,
)
from ..plugins import discover_plugins
from .currency_service import CurrencyCollector
from .digest_service import DailyDigestGenerator
from .github_service import GitHubTrendCollector
from .job_service import JobCollector
from .monitor_service import ServiceMonitorChecker
from .price_service import PriceCollector
from .promotions_service import PromotionsCollector
from .releases_service import ReleaseCollector
from .rss_service import RSSCollector
from .weather_service import WeatherCollector


class ScrapeOrchestrator:
    def __init__(self, app):
        self.app = app
        self.repo = Repository(app.config["DATABASE_TARGET"])
        self.logger = logging.getLogger(self.__class__.__name__)

        self.news_collector = RSSCollector(app, self.repo, NEWS_FEEDS, "news")
        self.ai_news_collector = RSSCollector(
            app,
            self.repo,
            AI_TECH_FEEDS,
            "tech_ai",
        )
        self.youtube_collector = RSSCollector(
            app,
            self.repo,
            YOUTUBE_CHANNEL_FEEDS,
            "youtube",
        )
        self.jobs_collector = JobCollector(app, self.repo, JOB_FEEDS, "job")

        self.promotions_collector = PromotionsCollector(app, self.repo)
        self.prices_collector = PriceCollector(app, self.repo)
        self.weather_collector = WeatherCollector(app, self.repo)
        self.github_collector = GitHubTrendCollector(app, self.repo)
        self.release_collector = ReleaseCollector(app, self.repo)
        self.currency_collector = CurrencyCollector(app, self.repo)
        self.monitor_checker = ServiceMonitorChecker(app, self.repo)
        self.digest_generator = DailyDigestGenerator(app, self.repo)

        # Plugin system
        self.plugin_registry = discover_plugins()
        for bp in self.plugin_registry.blueprints:
            try:
                app.register_blueprint(bp)
            except Exception:
                self.logger.exception("Failed to register plugin blueprint: %s", bp)

    def run_frequent_jobs(self) -> None:
        self.logger.info("Iniciando jobs frequentes")
        self._safe_run("notícias", self.news_collector)
        self._safe_run("tech/IA", self.ai_news_collector)
        self._safe_run("youtube", self.youtube_collector)
        self._safe_run("preços", self.prices_collector)
        self._safe_run("clima", self.weather_collector)
        self._safe_run("câmbio", self.currency_collector)
        self._safe_run("service monitor", self.monitor_checker)

        # Run plugin collectors
        plugin_results = self.plugin_registry.run_collectors(self.app, self.repo)
        for name, count in plugin_results.items():
            self.logger.info("plugin/%s: %s registros", name, count)

    def run_daily_jobs(self) -> None:
        self.logger.info("Iniciando jobs diários")
        self._safe_run("promoções", self.promotions_collector)
        self._safe_run("github trends", self.github_collector)
        self._safe_run("releases", self.release_collector)
        self._safe_run("jobs", self.jobs_collector)
        self._safe_run("daily digest", self.digest_generator)

        # Run plugin daily jobs
        self.plugin_registry.run_daily_jobs(self.app, self.repo)

    def _safe_run(self, label: str, collector) -> None:
        try:
            count = collector.run()
            self.logger.info("%s: %s novos registros", label, count)
        except Exception as exc:
            self.logger.exception("Falha em %s: %s", label, exc)
