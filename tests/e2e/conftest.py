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


def htmx_idle(page):
    """Wait until HTMX has finished every request, swap and settle, so freshly swapped
    content has its listeners. Call it after an action that redraws something and
    before typing into what was redrawn. People are far slower than this window; tests aren't."""
    page.wait_for_function(
        "() => window.htmx && !document.querySelector("
        "'.htmx-request, .htmx-swapping, .htmx-settling, .htmx-added')"
    )


@pytest.fixture(autouse=True)
def no_browser_errors(request):
    """Fail any browser test whose page logs a JavaScript or HTMX error (e.g. htmx:syntax:error
    from a malformed hx-trigger), even if the assertions it makes still pass."""
    if "page" not in request.fixturenames:
        yield
        return
    page = request.getfixturevalue("page")
    errors = []
    page.on("pageerror", lambda exc: errors.append(f"page error: {exc}"))

    def on_console(msg):
        if msg.type == "error":
            errors.append(f"console {msg.type}: {msg.text}")

    page.on("console", on_console)
    yield
    assert not errors, "Browser errors:\n" + "\n".join(errors)
