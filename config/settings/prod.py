"""Production settings. Every secret comes from the environment."""

import copy

from .base import *  # noqa: F403
from .base import TEMPLATES, env

DEBUG = False
SECRET_KEY = env("SECRET_KEY")

railway_domain = env("RAILWAY_PUBLIC_DOMAIN", default=None)
railway_static_url = env("RAILWAY_STATIC_URL", default=None)

default_allowed = ["localhost", "127.0.0.1", ".railway.app", ".up.railway.app"]
if railway_domain:
    default_allowed.append(railway_domain)
if railway_static_url:
    default_allowed.append(railway_static_url)

ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=default_allowed)
if railway_domain and railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(railway_domain)
if ".railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".railway.app")

default_csrf = ["https://*.railway.app", "https://*.up.railway.app"]
if railway_domain:
    default_csrf.append(f"https://{railway_domain}")
if railway_static_url:
    default_csrf.append(f"https://{railway_static_url}")

CSRF_TRUSTED_ORIGINS: list[str] = env.list("CSRF_TRUSTED_ORIGINS", default=default_csrf)
if railway_domain and f"https://{railway_domain}" not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(f"https://{railway_domain}")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

LOG_FORMAT = "json"

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@localhost")

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": env("EMAIL_HOST", default="localhost"),
            "port": env.int("EMAIL_PORT", default=587),
            "username": env("EMAIL_HOST_USER", default=""),
            "password": env("EMAIL_HOST_PASSWORD", default=""),
            "use_tls": env.bool("EMAIL_USE_TLS", default=True),
        },
    }
}

# --- Production Performance Optimizations ---

# Cached template loader: parse templates once, cache compiled result in memory
TEMPLATES = copy.deepcopy(TEMPLATES)
TEMPLATES[0]["OPTIONS"]["loaders"] = [
    (
        "django.template.loaders.cached.Loader",
        [
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ],
    ),
]
TEMPLATES[0]["APP_DIRS"] = False  # Required when using explicit loaders

# Session: read from Redis cache first, fallback to DB (eliminates 1 DB query/request)
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
