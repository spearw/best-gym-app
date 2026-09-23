import re

import pytest
from playwright.sync_api import Browser, Page, expect

from apps.accounts.models import Athlete

from ..conftest import PASSWORD

pytestmark = pytest.mark.django_db(transaction=True)


def test_coach_invites_and_athlete_onboards(page: Page, browser: Browser, base, coach):
    # Coach logs in through the real form.
    page.goto(base + "/")
    expect(page).to_have_url(re.compile(r"/accounts/login/"))
    page.get_by_label("Email").fill("dana@example.com")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()
    expect(page).to_have_url(base + "/coach/")
    expect(page.locator(".snav-foot")).to_contain_text("Dana Whitfield")

    # Invite from the Athletes page, link only.
    page.locator(".snav a.navitem", has_text="Athletes").click()
    expect(page.locator(".coach-topbar h2")).to_have_text("Athletes")
    page.get_by_role("button", name="+ Invite athlete").click()
    expect(page.locator(".modal.open")).to_be_visible()
    page.get_by_role("button", name="Create invite").click()
    link_box = page.locator("#invLink")
    expect(link_box).to_be_visible()
    join_url = link_box.input_value()
    assert "/join/" in join_url
    expect(page.locator("#toastStack .toast").first).to_contain_text("Invite link created")
    page.get_by_role("button", name="Done").click()
    expect(page.locator(".modal.open")).to_have_count(0)
    expect(page.locator("#inviteList")).to_contain_text("Link invite")  # refreshed via invitesChanged

    # The athlete opens the link on a phone, in a separate browser session.
    phone = browser.new_context(viewport={"width": 390, "height": 844}, timezone_id="America/Denver")
    athlete_page = phone.new_page()
    athlete_page.goto(join_url)
    expect(athlete_page.locator(".invite-card")).to_contain_text("Dana Whitfield — Iron Ridge Weightlifting")
    athlete_page.get_by_label("Name").fill("Nia Park")
    athlete_page.get_by_label("Email").fill("nia@example.com")
    athlete_page.get_by_label("Password").fill(PASSWORD)
    athlete_page.get_by_role("button", name="Create account").click()

    expect(athlete_page).to_have_url(re.compile(r"/app/welcome/$"))
    athlete_page.get_by_label(re.compile(r"^Bodyweight")).fill("61.5")
    athlete_page.get_by_label(re.compile(r"^Snatch 1RM")).fill("70")
    # Skip height: the input clears and disables.
    height = athlete_page.get_by_label(re.compile(r"^Height"))
    height.fill("165")
    athlete_page.locator(".field", has=height).locator(".skip").click()
    expect(height).to_be_disabled()
    athlete_page.get_by_role("button", name="Continue").click()

    expect(athlete_page.locator(".done-hero")).to_contain_text("You're all set")
    expect(athlete_page.locator(".done-hero")).to_contain_text(
        "4 fields left blank"
    )  # height skipped; C&J, squat, years left empty
    athlete_page.get_by_role("link", name="Show me my week →").click()
    expect(athlete_page).to_have_url(re.compile(r"/app/$"))
    expect(athlete_page.locator(".app-head")).to_contain_text("Hi, Nia")
    expect(athlete_page.locator(".app-head")).to_contain_text("Iron Ridge Weightlifting")
    phone.close()

    athlete = Athlete.objects.get(user__email="nia@example.com")
    assert athlete.user.timezone == "America/Denver"  # from the phone's browser
    assert athlete.height_cm is None
    assert str(athlete.current_bodyweight().kg) == "61.50"

    # Back on the coach's screen, the athlete shows up and the invite is gone.
    page.reload()
    expect(page.locator("#clientCards")).to_contain_text("Nia Park")
    expect(page.locator("#inviteList")).to_contain_text("No pending invites")


def test_settings_save_through_a_boosted_form_shows_a_toast(page: Page, base, coach, sign_in):
    sign_in(page, coach.user)
    page.goto(base + "/coach/settings/")
    page.get_by_label("Gym or team name").fill("Iron Ridge WL")
    page.get_by_role("button", name="Save settings").click()
    expect(page.locator("#toastStack .toast")).to_contain_text("Settings saved")
    expect(page.get_by_label("Gym or team name")).to_have_value("Iron Ridge WL")
