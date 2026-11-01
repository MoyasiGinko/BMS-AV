import socket

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


# Fallback to local memory cache for local development if Redis is not running
def _is_redis_available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 6379), timeout=0.1):
            return True
    except OSError:
        return False

if not _is_redis_available():
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dev-locmem",
        }
    }


