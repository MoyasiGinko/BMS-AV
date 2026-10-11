"""Test settings: fast hashing, eager Celery, in-memory cache/email.
Database stays PostgreSQL (RLS needs it).
"""

from .base import *  # noqa: F403

DEBUG = False
IS_TEST = True
NOTIFICATION_EMAIL_ADAPTER = "fake"
SECRET_KEY = "test-only-secret-key-not-for-production-use-0123456789"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    }
}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
ALLOWED_HOSTS = ["*"]
