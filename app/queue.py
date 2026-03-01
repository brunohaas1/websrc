from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_queue(config):
    if not config.get("QUEUE_ENABLED"):
        return None

    try:
        from redis import Redis
        from rq import Queue
    except ImportError:
        logger.warning(
            "RQ/Redis não instalados; "
            "fallback para execução síncrona.",
        )
        return None

    connection = Redis.from_url(config["REDIS_URL"])
    return Queue("scraping", connection=connection)
