"""
Django settings for the Southern Cross Auctions project.

All secrets and database credentials are read from a .env file in the
project root (see .env.example). Nothing sensitive is hardcoded here.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# BASE_DIR is the project root (the folder that contains manage.py).
BASE_DIR = Path(__file__).resolve().parent.parent

# Load the variables from .env into os.environ.
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    """Read an environment variable as True/False ("1", "true", "yes")."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Core settings
# ---------------------------------------------------------------------------

# The secret key must be set in .env; Django refuses to start without it.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = env_bool("DJANGO_DEBUG", default=False)

# Comma-separated list in .env, e.g. "localhost,127.0.0.1".
_hosts = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [host.strip() for host in _hosts.split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    # Project apps
    "accounts",
    "auctions",
    "payments",
    "notifications",
    "core",
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
        # Project-wide templates (e.g. base.html) live in /templates.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# True when the command is "python manage.py test".
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"

# DB_ENGINE in .env chooses the database: "mysql" (default) or "sqlite".
# Tests always use SQLite so they run without a MySQL server.
DB_ENGINE = "sqlite" if TESTING else os.getenv("DB_ENGINE", "mysql")

if DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.getenv("DB_NAME", "ict712_auction"),
            "USER": os.getenv("DB_USER", ""),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": os.getenv("DB_PORT", "3306"),
            "OPTIONS": {
                # utf8mb4 stores every Unicode character (including emoji).
                "charset": "utf8mb4",
                # Strict mode makes MySQL reject bad data instead of
                # silently truncating it.
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

# Our own User model with a role field (see accounts/models.py).
AUTH_USER_MODEL = "accounts.User"

_VALIDATORS = "django.contrib.auth.password_validation."

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": _VALIDATORS + "UserAttributeSimilarityValidator"},
    {"NAME": _VALIDATORS + "MinimumLengthValidator"},
    {"NAME": _VALIDATORS + "CommonPasswordValidator"},
    {"NAME": _VALIDATORS + "NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Internationalisation (Australia)
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-au"
TIME_ZONE = "Australia/Sydney"
USE_I18N = True
# Store datetimes in UTC and convert to Sydney time for display.
USE_TZ = True


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Email (printed to the console in development)
# ---------------------------------------------------------------------------

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "no-reply@southerncrossauctions.local"
)


# ---------------------------------------------------------------------------
# Django REST Framework and API docs
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Southern Cross Auctions API",
    "DESCRIPTION": "REST API for the Southern Cross Auctions platform.",
    "VERSION": "1.0.0",
}


# ---------------------------------------------------------------------------
# Celery (background tasks) with Redis as the message broker
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv(
    "CELERY_RESULT_BACKEND", "redis://localhost:6379/0"
)
CELERY_TIMEZONE = TIME_ZONE
# During tests, run tasks immediately in the same process (no Redis needed).
CELERY_TASK_ALWAYS_EAGER = TESTING


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

# When False, the "Pay now" step is mocked. When True, Stripe test mode
# is used with the keys below.
USE_STRIPE = env_bool("USE_STRIPE", default=False)
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
