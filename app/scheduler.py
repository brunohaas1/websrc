from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from rq import Retry

from .jobs import run_daily_scrape, run_frequent_scrape
from .queue import get_queue
from .services.orchestrator import ScrapeOrchestrator
from .utils import setup_logging


class ScraperScheduler:
    def __init__(self, app):
        self.app = app
        setup_logging(
            app.config["LOG_LEVEL"],
            log_json=app.config["LOG_JSON"],
        )
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.orchestrator = ScrapeOrchestrator(app)
        self.queue = get_queue(app.config)

    def start(self) -> None:
        if self.scheduler.running:
            return

        interval = self.app.config["SCRAPE_INTERVAL_MINUTES"]
        daily_hours = self.app.config["DAILY_INTERVAL_HOURS"]

        self.scheduler.add_job(
            self.enqueue_frequent,
            "interval",
            minutes=interval,
            id="frequent",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )
        self.scheduler.add_job(
            self.enqueue_daily,
            "interval",
            hours=daily_hours,
            id="daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
        )

        self.scheduler.start()
        self.enqueue_frequent()
        self.enqueue_daily()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def run_all_now(self) -> None:
        self.enqueue_frequent()
        self.enqueue_daily()

    def enqueue_frequent(self):
        if self.queue is None:
            self.orchestrator.run_frequent_jobs()
            return None

        return self.queue.enqueue(
            run_frequent_scrape,
            self.app.config["DATABASE_TARGET"],
            self.app.config["LOG_LEVEL"],
            job_timeout="10m",
            retry=Retry(max=3, interval=[30, 60, 120]),
            failure_ttl=86400,
        )

    def enqueue_daily(self):
        if self.queue is None:
            self.orchestrator.run_daily_jobs()
            return None

        return self.queue.enqueue(
            run_daily_scrape,
            self.app.config["DATABASE_TARGET"],
            self.app.config["LOG_LEVEL"],
            job_timeout="20m",
            retry=Retry(max=3, interval=[30, 60, 120]),
            failure_ttl=86400,
        )
