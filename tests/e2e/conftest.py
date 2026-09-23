import os

import pytest
from django.conf import settings
from django.test import Client

# Playwright's sync API runs an event loop in the test thread; Django's ORM refuses
# to run inside one unless told it is safe (the live server runs in its own thread).
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture
def base(live_server):
    return live_server.url


@pytest.fixture
def sign_in(live_server):
    """Sign a Playwright page in as a user without going through the login form."""

    def do(page, user):
        client = Client()
        client.force_login(user)
        cookie = client.cookies[settings.SESSION_COOKIE_NAME]
        page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie.value, "url": live_server.url}]
        )

    return do
