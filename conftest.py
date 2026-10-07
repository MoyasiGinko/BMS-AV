"""Project-wide pytest fixtures. Factories live in tests/factories/."""

import os

# Enable synchronous Django ORM operations when running inside Playwright/async test runners
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
