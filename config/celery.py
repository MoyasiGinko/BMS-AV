"""Celery application. Queues and beat schedule are configured in settings (CELERY_* keys)."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("business_os")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
