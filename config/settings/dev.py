"""Local development settings."""

from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = ["*"]

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    }
}
INTERNAL_IPS = ["127.0.0.1"]
