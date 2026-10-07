"""Settings used only by `check --deploy` in the verify gate: prod settings with safe placeholder secrets."""

import os

os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
os.environ["SECRET_KEY"] = (
    "prod-check-safe-placeholder-secret-key-at-least-50-chars-x7Kq2pVz9LmN4rT8wB1cY6hJ3dF5gS0aE"
)
os.environ["ALLOWED_HOSTS"] = "example.com"

from .prod import *  # noqa: F403

SECRET_KEY = "prod-check-safe-placeholder-secret-key-at-least-50-chars-x7Kq2pVz9LmN4rT8wB1cY6hJ3dF5gS0aE"
ALLOWED_HOSTS = ["example.com"]
