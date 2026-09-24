import json

import pytest
from django.core.management import call_command
from django.test import override_settings

pytestmark = pytest.mark.django_db


def test_healthz_touches_database(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@override_settings(ALLOWED_HOSTS=["gymtrainer.onrender.com"], SECURE_SSL_REDIRECT=True)
def test_healthz_skips_host_check_and_https_redirect(client):
    # Render's internal probe: plain HTTP, unknown Host header.
    response = client.get("/healthz", HTTP_HOST="10.0.0.12:10000")
    assert response.status_code == 200


def test_index_sends_visitors_to_login(client):
    response = client.get("/")
    assert response.status_code == 302 and response["Location"] == "/accounts/login/"


@pytest.mark.parametrize(
    "url,active",
    [
        ("/coach/", "Dashboard"),
        ("/coach/athletes/", "Athletes"),
        ("/coach/programming/exercises/", "Programming"),
        ("/coach/settings/", "Settings"),
    ],
)
def test_coach_shell_marks_active_nav(coach_client, url, active):
    html = coach_client.get(url).content.decode()
    assert 'class="coach-shell"' in html
    assert 'hx-boost="true"' in html
    nav_href = "/coach/programming/" if active == "Programming" else url
    assert f'navitem active" href="{nav_href}"' in html
    title = "<h2>Good " if active == "Dashboard" else f"<h2>{active}</h2>"  # the dashboard greets the coach
    assert title in html
    assert "Dana Whitfield" in html  # real signed-in coach in the sidebar


@pytest.mark.parametrize("url", ["/app/", "/app/progress/", "/app/coach/", "/app/profile/"])
def test_athlete_shell_renders(athlete_client, url):
    html = athlete_client.get(url).content.decode()
    assert 'class="phone"' in html and 'id="mTabbar"' in html
    assert f'class="active" href="{url}"' in html


def test_base_layout_loads_htmx_alpine_and_ported_css(coach_client):
    html = coach_client.get("/coach/").content.decode()
    for asset in [
        "htmx-2.0.11.min.js",
        "alpine-3.17.4.min.js",
        "css/tokens.css",
        "css/icons.css",
        "css/app.css",
        "js/app.js",
    ]:
        assert asset in html
    assert '"X-CSRFToken"' in html  # CSRF header for every HTMX request


def test_nightly_command_runs(capsys):
    call_command("nightly")
    assert "synced alerts" in capsys.readouterr().out


def test_boosted_coach_request_returns_only_main_and_oob_nav(coach_client):
    html = coach_client.get(
        "/coach/athletes/", HTTP_HX_REQUEST="true", HTTP_HX_BOOSTED="true", HTTP_HX_TARGET="coach-main"
    ).content.decode()
    assert "<aside" not in html and "<html" not in html
    assert 'id="coach-main"' in html
    assert 'id="snav-links" class="stack" style="gap:2px" hx-swap-oob="true"' in html
    assert "<title>Athletes · Platform</title>" in html


def test_boosted_app_request_returns_only_body_and_oob_tabbar(athlete_client):
    html = athlete_client.get(
        "/app/profile/", HTTP_HX_REQUEST="true", HTTP_HX_BOOSTED="true", HTTP_HX_TARGET="app-body"
    ).content.decode()
    assert 'class="phone"' not in html and 'id="app-body"' in html
    assert 'id="mTabbar" hx-swap-oob="true"' in html


def test_hx_trigger_header_is_ascii_json_even_with_unicode():
    from django.http import HttpResponse

    from apps import hx

    response = hx.toast(HttpResponse(), "Link created — share it", "good")
    header = response["HX-Trigger"]
    assert header.isascii()
    assert json.loads(header)["toast"]["message"] == "Link created — share it"


def test_no_template_uses_a_multiline_short_comment():
    """Django's {# #} comments are single-line: a multi-line one renders as text on the page."""
    import re
    from pathlib import Path

    bad = [
        str(path)
        for path in Path("templates").rglob("*.html")
        if any("\n" in m for m in re.findall(r"\{#(.*?)#\}", path.read_text(), re.S))
    ]
    assert not bad, f"Use {{% comment %}} for multi-line comments in: {bad}"
