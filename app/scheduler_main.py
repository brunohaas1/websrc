import time

from app import create_app


def main() -> None:
    create_app(start_scheduler=True)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
