import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.django_db(transaction=True)


def test_coach_shell_boosted_navigation_keeps_sidebar(page: Page, base, coach, sign_in):
    sign_in(page, coach.user)
    page.goto(base + "/")
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


def test_athlete_shell_fills_a_phone_screen_and_tabs_work(page: Page, base, athlete, sign_in):
    sign_in(page, athlete.user)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base + "/")
    expect(page).to_have_url(base + "/app/")
    phone = page.locator(".phone")
    expect(phone).to_be_visible()
    box = phone.bounding_box()
    assert box["width"] == 390 and box["height"] == 844
    expect(page.locator(".app-head")).to_contain_text("Hi, Maya")

    page.locator("#mTabbar a", has_text="Progress").click()
    expect(page).to_have_url(base + "/app/progress/")
    expect(page.locator("#mTabbar a.active")).to_have_text("Progress")
    expect(page.locator("#app-body h3")).to_have_text("Your progress")


def test_coach_pages_open_at_the_top(page: Page, base, coach, sign_in):
    """Boosted navigation swaps only the main area; each new page still starts at the top."""
    from apps.library.models import TemplateKind
    from apps.library.services import add_week, new_template

    template = new_template(coach.gym, TemplateKind.PROGRAM, coach.user)
    for _ in range(6):
        add_week(template)  # a long editor page to scroll down
    sign_in(page, coach.user)
    for link, url in [("Programming", "/coach/programming/templates/"), ("Settings", "/coach/settings/")]:
        page.goto(base + f"/coach/library/{template.pk}/")
        page.mouse.wheel(0, 3000)
        page.wait_for_function("() => window.scrollY > 500")
        page.locator("a.navitem", has_text=link).click()
        expect(page).to_have_url(base + url)
        page.wait_for_function("() => window.scrollY === 0")
        page.wait_for_timeout(300)  # and it stays there once HTMX has settled
        assert page.evaluate("window.scrollY") == 0
    expect(page.locator("h2").first).to_be_in_viewport()
