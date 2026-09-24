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

# Form videos go to the MinIO container from docker-compose.yml unless STORAGE_* is set.
if not FORM_VIDEOS["endpoint"]:  # noqa: F405
    FORM_VIDEOS.update(  # noqa: F405
        endpoint="http://localhost:9000",
        bucket="gymtrainer-videos",
        access_key="gymtrainer",
        secret="gymtrainer-local-only",
        region="us-east-1",
    )
