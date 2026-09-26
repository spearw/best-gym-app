"""The "Report a bug" button in a real browser, from the coach's top bar and the phone header."""

import pytest
from playwright.sync_api import Page, expect

from apps.dashboard.models import BugReport

from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)


def report(page, text):
    modal = page.locator(".modal.open")
    expect(modal).to_contain_text("Report a bug")
    htmx_idle(page)
    modal.get_by_label("What went wrong?").fill(text)
    modal.get_by_role("button", name="Send report").click()
    expect(page.locator(".modal.open")).to_have_count(0)
    expect(page.locator("#toastStack")).to_contain_text("Thanks — your bug report was sent")


def test_reporting_a_bug_from_both_apps(page: Page, base, coach, athlete, sign_in):
    sign_in(page, coach.user)
    page.goto(base + "/coach/athletes/")
    page.get_by_role("button", name="Report a bug").click()
    report(page, "The roster filter forgets my choice")

    sign_in(page, athlete.user)
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(base + "/app/progress/")
    page.get_by_role("button", name="Report a bug").click()
    report(page, "Chart is blank on my phone")

    coach_report, athlete_report = BugReport.objects.order_by("created_at")
    assert coach_report.side == "coach" and coach_report.page.endswith("/coach/athletes/")
    assert athlete_report.side == "athlete" and athlete_report.page.endswith("/app/progress/")
    assert athlete_report.screen == "390×800"
