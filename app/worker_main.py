from redis import Redis
from rq import Worker

from .config import Config
from .utils import setup_logging


def main() -> None:
    setup_logging(Config.LOG_LEVEL, log_json=Config.LOG_JSON)
    redis_conn = Redis.from_url(Config.REDIS_URL)

    worker = Worker(["scraping"], connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
