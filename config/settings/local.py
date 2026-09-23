import warnings

from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "local-dev-only-not-secret"  # noqa: F405
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}

# WhiteNoise warns that STATIC_ROOT does not exist; in development runserver serves static files itself.
warnings.filterwarnings("ignore", message="No directory at", module="whitenoise.base")
