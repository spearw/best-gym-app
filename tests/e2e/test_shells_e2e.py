import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.django_db(transaction=True)


def test_coach_shell_boosted_navigation_keeps_sidebar(page: Page, base):
    page.goto(base + "/")
    page.get_by_role("link", name=re.compile("Coach app")).click()
    expect(page).to_have_url(base + "/coach/")
    expect(page.locator(".snav")).to_be_visible()
    assert page.evaluate("typeof window.htmx") == "object"
    assert page.evaluate("typeof window.Alpine") == "object"

    # Mark the sidebar node; a boosted swap must keep the same element, not reload the page.
    page.evaluate("document.querySelector('.snav').dataset.marker = 'kept'")
    page.locator(".snav a.navitem", has_text="Athletes").click()
    expect(page).to_have_url(base + "/coach/athletes/")
    expect(page.locator(".coach-topbar h2")).to_have_text("Athletes")
    assert page.evaluate("document.querySelector('.snav').dataset.marker") == "kept"
    expect(page.locator(".snav a.navitem.active")).to_have_text("Athletes")
    expect(page).to_have_title(re.compile("Athletes"))

    # The ported CSS is applied: the sidebar uses the mockup's --ink colour.
    bg = page.evaluate("getComputedStyle(document.querySelector('.snav')).backgroundColor")
    assert bg == "rgb(20, 24, 31)"


def test_htmx_ping_swaps_fragment_and_shows_toast(page: Page, base):
    page.goto(base + "/coach/programming/")
    page.get_by_role("button", name="Ping the server").click()
    expect(page.locator("#pingResult")).to_have_text("HTMX is wired")
    expect(page.locator("#toastStack .toast")).to_have_text("Server replied")


def test_athlete_shell_fills_a_phone_screen_and_tabs_work(page: Page, base):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base + "/app/")
    phone = page.locator(".phone")
    expect(phone).to_be_visible()
    box = phone.bounding_box()
    assert box["width"] == 390 and box["height"] == 844
    expect(page.locator(".phone-exit")).to_be_hidden()

    page.locator("#mTabbar a", has_text="Progress").click()
    expect(page).to_have_url(base + "/app/progress/")
    expect(page.locator("#mTabbar a.active")).to_have_text("Progress")
    expect(page.locator("#app-body h3")).to_have_text("Your progress")
