"""Celery application bootstrap.

Tasks live in `apps.payouts.tasks`. The Beat schedule (stuck-payout watchdog
and idempotency cleanup) is registered in `apps.payouts.tasks` via
`@app.on_after_configure.connect` so that schedules survive worker restarts.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("playto")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
