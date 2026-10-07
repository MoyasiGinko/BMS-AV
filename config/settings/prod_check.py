"""Settings used only by `check --deploy` in the verify gate: prod settings with safe placeholder secrets."""

import os

os.environ.setdefault("SECRET_KEY", "prod-check-placeholder-" + "x7Kq2pVz9LmN4rT8wB1cY6hJ3dF5gS0aE")
os.environ.setdefault("ALLOWED_HOSTS", "example.com")

from .prod import *  # noqa: F403
