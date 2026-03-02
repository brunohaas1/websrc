import signal
import sys
import time

from app import create_app

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    app = create_app(start_scheduler=True)

    while not _shutdown:
        time.sleep(1)

    scheduler = getattr(app, "scheduler", None)
    if scheduler is not None:
        scheduler.shutdown()

    sys.exit(0)


if __name__ == "__main__":
    main()
