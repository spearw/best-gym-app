from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

if not SECRET_KEY:  # noqa: F405
    raise ImproperlyConfigured("SECRET_KEY must be set in production")

DEBUG = False

# Render terminates TLS at its proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Render's own hostname is always allowed alongside anything in ALLOWED_HOSTS.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")  # noqa: F405
if _render_host:
    ALLOWED_HOSTS.append(_render_host)  # noqa: F405
    CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")  # noqa: F405

# HSTS preload is hard to undo and needs a real domain first; revisit when one is bought.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
