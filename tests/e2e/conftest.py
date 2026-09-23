import os

import pytest

# Playwright's sync API runs an event loop in the test thread; Django's ORM refuses
# to run inside one unless told it is safe (the live server runs in its own thread).
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture
def base(live_server):
    return live_server.url
