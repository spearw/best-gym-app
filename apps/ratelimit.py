"""Simple rate limits for the endpoints worth abusing: sign-in, password reset, sign-up,
invite links, messages, video uploads, invites. Counts live in the database cache, so all
of the web workers share them.

    @rate_limit("login", 10, 15 * 60, key=by_ip)

Over the limit, a request gets a 429 (an HTMX request gets a toast instead of a page).
"""

import time
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import render

from apps import hx


def client_ip(request):
    """Render's proxy appends the address it saw to X-Forwarded-For; the last entry is the
    one a client can't fake."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def by_ip(request):
    return client_ip(request)


def by_user(request):
    return f"user:{request.user.pk}" if request.user.is_authenticated else f"ip:{client_ip(request)}"


def hit(name, key, limit, window):
    """Count one attempt; True if it's within the limit. Fixed windows of `window` seconds."""
    bucket = int(time.time() // window)
    cache_key = f"rl:{name}:{key}:{bucket}"
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.add(cache_key, 0, timeout=window + 60)
        count = cache.incr(cache_key)
    return count <= limit


def too_many(request, message="Too many attempts. Wait a few minutes and try again."):
    if getattr(request, "htmx", False):
        return hx.toast(HttpResponse(status=429), message, "err")
    return render(request, "429.html", {"message": message}, status=429)


def rate_limit(name, limit, window, key=by_ip, methods=("POST",)):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method in methods and not hit(name, key(request), limit, window):
                return too_many(request)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
