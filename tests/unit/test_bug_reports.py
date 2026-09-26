"""The "Report a bug" button in both headers, the reports in the admin, and ensure_admin."""

import json

import pytest
from django.core.management import call_command
from django.test import Client

from apps.accounts.models import User
from apps.dashboard.models import BugReport

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def test_both_headers_have_the_button(coach_client, athlete):
    assert "Report a bug" in coach_client.get("/coach/").content.decode()
    client = Client()
    client.force_login(athlete.user)
    assert 'aria-label="Report a bug"' in client.get("/app/").content.decode()


def test_a_report_captures_the_page_and_device(athlete, coach):
    client = Client()
    client.force_login(athlete.user)
    modal = client.get(
        "/feedback/bug/?side=athlete", HTTP_HX_CURRENT_URL="https://site.example/app/progress/", **HX
    ).content.decode()
    assert "Report a bug" in modal and 'value="https://site.example/app/progress/"' in modal
    response = client.post(
        "/feedback/bug/",
        {
            "side": "athlete",
            "description": "The chart is blank",
            "page": "https://site.example/app/progress/",
            "screen": "390×844",
        },
        HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14)",
        **HX,
    )
    assert json.loads(response["HX-Trigger"])["toast"]["message"].startswith("Thanks")
    report = BugReport.objects.get()
    assert (report.user, report.gym, report.side, report.status) == (
        athlete.user,
        coach.gym,
        "athlete",
        "new",
    )
    assert (
        report.page.endswith("/app/progress/")
        and report.screen == "390×844"
        and "Android" in report.user_agent
    )


def test_an_empty_report_is_refused(coach_client):
    html = coach_client.post("/feedback/bug/", {"side": "coach", "description": " "}, **HX).content.decode()
    assert "Describe the problem first." in html and not BugReport.objects.exists()


def test_reports_need_a_sign_in(client):
    assert client.get("/feedback/bug/")["Location"].startswith("/accounts/login/")


def test_reports_are_listed_in_the_admin(coach, athlete, monkeypatch):
    BugReport.objects.create(
        user=athlete.user, side="athlete", description="Save button froze", page="javascript:alert(1)"
    )
    monkeypatch.setenv("ADMIN_EMAIL", "steven@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "a-long-admin-password")
    call_command("ensure_admin")
    admin = Client()
    admin.force_login(User.objects.get(email="steven@example.com"))
    listing = admin.get("/admin/dashboard/bugreport/").content.decode()
    assert "Save button froze" in listing
    detail = admin.get(f"/admin/dashboard/bugreport/{BugReport.objects.get().pk}/change/").content.decode()
    assert 'href="javascript:' not in detail  # a page address from the browser never becomes a script link


def test_ensure_admin(monkeypatch, athlete):
    call_command("ensure_admin")  # nothing set: nothing happens
    assert not User.objects.filter(is_superuser=True).exists()
    monkeypatch.setenv("ADMIN_EMAIL", "Steven@Example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    call_command("ensure_admin")
    assert not User.objects.filter(is_superuser=True).exists()
    monkeypatch.setenv("ADMIN_PASSWORD", "a-long-admin-password")
    call_command("ensure_admin")
    admin = User.objects.get(email="steven@example.com")
    assert admin.is_superuser and admin.is_staff and admin.check_password("a-long-admin-password")
    monkeypatch.setenv("ADMIN_PASSWORD", "a-new-long-password")
    call_command("ensure_admin")
    admin.refresh_from_db()
    assert admin.check_password("a-new-long-password") and User.objects.filter(is_superuser=True).count() == 1


def test_service_worker_cache_changes_with_the_files(tmp_path, monkeypatch):
    """Locally static URLs carry no hash, so the worker's cache must follow the files'
    contents, or a changed stylesheet (like a new icon) never reaches the browser."""
    from apps.dashboard import pwa

    css = tmp_path / "shell.css"
    css.write_text(".a{}")
    monkeypatch.setattr(pwa.finders, "find", lambda path: str(css))
    before = pwa._version(["/static/css/shell.css"])
    css.write_text(".a{} .svgi--bug{}")
    assert pwa._version(["/static/css/shell.css"]) != before
