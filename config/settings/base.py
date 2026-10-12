"""Base settings shared by every environment. Values come from the environment (django-environ)."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import environ
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    environ.Env.read_env(str(_env_file))

SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-secret-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", ".localhost"])
BASE_DOMAIN = env("BASE_DOMAIN", default="localhost")

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "django_htmx",
    "django_tailwind_cli",
    "allauth",
    "allauth.account",
    "allauth.mfa",
]
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.tenancy",
    "apps.billing",
    "apps.backoffice",
    "apps.accounting",
    "apps.catalog",
    "apps.inventory",
    "apps.customers",
    "apps.sales",
    "apps.pos",
    "apps.reports",
    "apps.integrations",
    "apps.purchasing",
    "apps.crm",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.TenantMiddleware",
    "apps.billing.middleware.SubscriptionReadOnlyMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://postgres:postgres@127.0.0.1:5433/bos"),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DATABASES["default"]["CONN_MAX_AGE"] = 0  # Pooling handles connection lifecycle
DATABASES["default"]["OPTIONS"] = {}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# Django 6.1 Mailers (see docs/STACK.md)
MAILERS: dict[str, Any] = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    }
}

# Built-in Content Security Policy (see docs/STACK.md)
SECURE_CSP = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'"],
    "connect-src": ["'self'"],
    "frame-ancestors": ["'none'"],
}

# i18n / l10n
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="dev-only-32-byte-base64-key-change-me")

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.api.authentication.ApiKeyAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.api.pagination.StandardCursorPagination",
    "EXCEPTION_HANDLER": "apps.core.api.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.core.api.throttling.ApiKeyRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "tenant_user": "1000/minute",
        "tenant_anon": "100/minute",
        "api_key": "60/minute",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Business OS API",
    "DESCRIPTION": "Multi-tenant business management platform REST API (v1).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            },
        },
    },
    "ENUM_NAME_OVERRIDES": {
        "CustomerStatusEnum": "apps.customers.models.CustomerStatus",
        "CustomerTypeEnum": "apps.customers.models.CustomerType",
        "CustomerAddressTypeEnum": "apps.customers.models.AddressType",
        "CustomerBalanceEntryTypeEnum": "apps.customers.models.BalanceEntryType",
        "ProductTypeEnum": "apps.catalog.models.ProductType",
        "StockMovementTypeEnum": "apps.inventory.models.MovementType",
        "StockTransferStatusEnum": "apps.inventory.models.TransferStatus",
        "StockCountStatusEnum": "apps.inventory.models.CountStatus",
        "StockReservationStatusEnum": "apps.inventory.models.ReservationStatus",
        "StockAdjustmentReasonEnum": "apps.inventory.models.AdjustmentReason",
        "QuoteStatusEnum": "apps.sales.models.QuoteStatus",
        "SalesOrderStatusEnum": "apps.sales.models.SalesOrderStatus",
        "InvoiceStatusEnum": "apps.sales.models.InvoiceStatus",
        "CreditNoteStatusEnum": "apps.sales.models.CreditNoteStatus",
        "PaymentMethodEnum": "apps.sales.models.PaymentMethod",
        "PurchaseOrderStatusEnum": "apps.purchasing.models.PurchaseOrderStatus",
        "GoodsReceiptStatusEnum": "apps.purchasing.models.GoodsReceiptStatus",
        "SupplierPaymentMethodEnum": "apps.purchasing.models.SupplierPaymentMethod",
        "PurchaseReturnStatusEnum": "apps.purchasing.models.PurchaseReturnStatus",
        "AccountTypeEnum": "apps.accounting.models.AccountType",
        "JournalEntryStatusEnum": "apps.accounting.models.JournalEntryStatus",
        "FiscalPeriodStatusEnum": "apps.accounting.models.FiscalPeriodStatus",
        "BankTransactionTypeEnum": "apps.accounting.models.BankTransactionType",
        "BankReconciliationStatusEnum": "apps.accounting.models.BankReconciliationStatus",
        "ExpensePaymentMethodEnum": "apps.accounting.models.ExpensePaymentMethod",
        "TaxSummaryStatusEnum": "apps.accounting.models.TaxSummaryStatus",
    },
    "SECURITY": [{"BearerAuth": []}],
}

CORS_ALLOWED_ORIGINS: list[str] = env.list("CORS_ALLOWED_ORIGINS", default=[])

# Tailwind standalone CLI
TAILWIND_CLI_VERSION = "4.3.3"

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = "UTC"
CELERY_TASK_QUEUES = {
    "default": {"exchange": "default", "routing_key": "default"},
    "high": {"exchange": "high", "routing_key": "high"},
    "low": {"exchange": "low", "routing_key": "low"},
}
CELERY_BEAT_SCHEDULE = {
    "dispatch-outbox-events": {
        "task": "core.dispatch_outbox_events",
        "schedule": 10.0,
    },
    "process-due-recurring-invoices": {
        "task": "sales.process_due_recurring_invoices",
        "schedule": 3600.0,
    },
    "dispatch-due-payment-reminders": {
        "task": "sales.dispatch_due_payment_reminders",
        "schedule": 86400.0,
    },
}

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# allauth settings
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "optional"
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/accounts/login/"

MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
MFA_PASSKEY_LOGIN_ENABLED = False

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Structured Observability & Logging
LOG_FORMAT = env("LOG_FORMAT", default="json" if not DEBUG else "verbose")
LOG_LEVEL = env("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "apps.core.logging.JSONLogFormatter",
        },
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

# Sentry error tracking
SENTRY_DSN = env("SENTRY_DSN", default="")
SENTRY_TRACES_SAMPLE_RATE = env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1)
ENVIRONMENT = env("ENVIRONMENT", default="development" if DEBUG else "production")
