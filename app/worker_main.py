import logging
import sys
import time

from redis import Redis
from rq import Worker

from .config import Config
from .utils import setup_logging


def main() -> None:
    setup_logging(Config.LOG_LEVEL, log_json=Config.LOG_JSON)
    logger = logging.getLogger(__name__)

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            redis_conn = Redis.from_url(Config.REDIS_URL)
            redis_conn.ping()
            break
        except Exception as exc:
            logger.warning(
                "Redis connection attempt %d/%d failed: %s",
                attempt, max_retries, exc,
            )
            if attempt == max_retries:
                logger.error("Could not connect to Redis after %d attempts", max_retries)
                sys.exit(1)
            time.sleep(min(2 ** attempt, 30))

    worker = Worker(["scraping"], connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
