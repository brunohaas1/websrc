from redis import Redis
from rq import Connection, Worker

from .config import Config
from .utils import setup_logging


def main() -> None:
    setup_logging(Config.LOG_LEVEL)
    redis_conn = Redis.from_url(Config.REDIS_URL)

    with Connection(redis_conn):
        worker = Worker(["scraping"])
        worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
