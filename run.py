from app import create_app


app = create_app()


if __name__ == "__main__":
    # Development runner
    app.run(host="0.0.0.0", port=5000)
import os

from app import create_app

role = os.getenv("APP_ROLE", "all")
app = create_app(start_scheduler=role in {"all", "scheduler"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
