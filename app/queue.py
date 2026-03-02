from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_queue(config: dict[str, Any]) -> Any:
    if not config.get("QUEUE_ENABLED"):
        return None

    try:
        from rq import Queue

        from .cache import get_redis_client

        connection = get_redis_client(config)
        return Queue("scraping", connection=connection)
    except ImportError:
        logger.warning(
            "RQ/Redis não instalados; "
            "fallback para execução síncrona.",
        )
        return None
