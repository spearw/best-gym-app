"""Settings shared by every environment. See docs/BUILD_PLAN.md, "Stack and architecture"."""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.postgres",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django_htmx",
    "template_partials",
    "anymail",
    "apps.accounts",
    "apps.exercises",
    "apps.library",
    "apps.programs",
    "apps.workouts",
    "apps.messaging",
    "apps.dashboard",
]

MIDDLEWARE = [
    "apps.dashboard.middleware.HealthCheckMiddleware",  # first: see its docstring
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.accounts.middleware.UserTimezoneMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.dashboard.context_processors.shell_frames",
                "apps.accounts.context_processors.gym",
            ],
        },
    },
]

# Postgres everywhere, including locally (docker compose up db). No SQLite.
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default="postgres://gymtrainer:gymtrainer@localhost:5432/gymtrainer",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "index"
LOGOUT_REDIRECT_URL = "accounts:login"
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # reset links last one day
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # stored in UTC; "today" is computed in the athlete's or gym's zone
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email: invites and password resets. Set EMAIL_PROVIDER to "resend" or "postmark"
# and EMAIL_API_KEY to send for real; otherwise email is printed to the console.
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Platform <no-reply@localhost>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "").lower()
_email_key = os.environ.get("EMAIL_API_KEY", "")
if EMAIL_PROVIDER == "resend" and _email_key:
    EMAIL_BACKEND = "anymail.backends.resend.EmailBackend"
    ANYMAIL = {"RESEND_API_KEY": _email_key}
elif EMAIL_PROVIDER == "postmark" and _email_key:
    EMAIL_BACKEND = "anymail.backends.postmark.EmailBackend"
    ANYMAIL = {"POSTMARK_SERVER_TOKEN": _email_key}
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"line": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "line"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
