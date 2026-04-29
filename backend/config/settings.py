"""Django settings for the Playto Payout Engine.

Environment-driven via django-environ. All money-relevant tunables (settlement
simulation rates, retry counts, idempotency TTL) are exposed as env vars so the
behaviour can be toggled in tests and demos without code changes.
"""

from pathlib import Path
import os

import environ

BASE_DIR = Path(__file__).resolve().parent.parent


def _ensure_rediss_ssl_cert_reqs(url: str) -> str:
    """Celery 5.4+ validates rediss:// URLs and requires ssl_cert_reqs in the query
    string (celery.backends.redis); backend SSL dict alone is not read early enough.
    """
    if not url.startswith("rediss://"):
        return url
    if "ssl_cert_reqs=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}ssl_cert_reqs=CERT_REQUIRED"


env = environ.Env(
    DEBUG=(bool, False),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-do-not-use-in-prod")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "django_celery_beat",
    "apps.merchants",
    "apps.ledger",
    "apps.payouts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://playto:playto@localhost:5432/playto",
    ),
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 25,
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "EXCEPTION_HANDLER": "apps.payouts.exceptions.payout_exception_handler",
}

# --- Celery ---------------------------------------------------------------
CELERY_BROKER_URL = _ensure_rediss_ssl_cert_reqs(
    env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
)
CELERY_RESULT_BACKEND = _ensure_rediss_ssl_cert_reqs(
    env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
)
# Celery 5.4 + Kombu may read broker/backend from os.environ; PM2 injects .env
# before Django loads. Overwrite so rediss:// always includes ssl_cert_reqs.
os.environ["CELERY_BROKER_URL"] = CELERY_BROKER_URL
os.environ["CELERY_RESULT_BACKEND"] = CELERY_RESULT_BACKEND

CELERY_TASK_TRACK_STARTED = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_BEAT_SCHEDULE = {
    "scan-stuck-payouts-every-10s": {
        "task": "payouts.scan_stuck_payouts",
        "schedule": 10.0,
    },
    "cleanup-expired-idempotency-keys-hourly": {
        "task": "payouts.cleanup_expired_idempotency_keys",
        # Run once an hour - cheap and bounds the table size more tightly.
        "schedule": 3600.0,
    },
}

# --- Payout simulation / retry ------------------------------------------
PAYOUT_SUCCESS_RATE = env.float("PAYOUT_SUCCESS_RATE", default=0.70)
PAYOUT_FAILURE_RATE = env.float("PAYOUT_FAILURE_RATE", default=0.20)
PAYOUT_HANG_RATE = env.float("PAYOUT_HANG_RATE", default=0.10)
# Fail-fast on misconfiguration: the simulator picks an outcome by
# weighted random over these three, so they must sum to 1.0. Without
# this assert a typo (e.g. 0.7 / 0.2 / 0.05) silently degrades the
# simulation distribution.
assert abs(
    (PAYOUT_SUCCESS_RATE + PAYOUT_FAILURE_RATE + PAYOUT_HANG_RATE) - 1.0
) < 1e-6, "PAYOUT_SUCCESS_RATE + PAYOUT_FAILURE_RATE + PAYOUT_HANG_RATE must sum to 1.0"
PAYOUT_STUCK_AFTER_SECONDS = env.int("PAYOUT_STUCK_AFTER_SECONDS", default=30)
PAYOUT_MAX_ATTEMPTS = env.int("PAYOUT_MAX_ATTEMPTS", default=3)
PAYOUT_RETRY_BASE_DELAY_SECONDS = env.int("PAYOUT_RETRY_BASE_DELAY_SECONDS", default=5)

# --- Idempotency ---------------------------------------------------------
IDEMPOTENCY_TTL_HOURS = env.int("IDEMPOTENCY_TTL_HOURS", default=24)
# If an idempotency row exists without a cached response (rare: orphaned row
# or edge-case races), POST retries until this timeout then returns 409.
IDEMPOTENCY_IN_FLIGHT_WAIT_SECONDS = env.int(
    "IDEMPOTENCY_IN_FLIGHT_WAIT_SECONDS", default=30
)

# --- Logging -------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}
