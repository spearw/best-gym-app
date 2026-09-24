"""Phase 8 in a real browser: a form video goes from the phone to the bucket (MinIO here,
Cloudflare R2 in production) and the coach reviews it; and every main page passes an
automated accessibility check (axe-core)."""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from apps.exercises.models import Exercise
from apps.messaging.models import Message
from apps.programs import services as program_services
from apps.programs.models import WeekType
from apps.workouts import sessions
from apps.workouts.models import FormVideo

from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)
AXE = (Path(__file__).parent / "vendor" / "axe-4.10.2.min.js").read_text()


@pytest.fixture
def todays_session(athlete, coach):
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    program = program_services.start_program(athlete, "Block", athlete.today(), 1, week_type, by=coach.user)
    week = program.weeks.get()
    program_services.set_published(week, True)
    day = week.days.get(date=athlete.today())
    program_services.add_prescription(day, Exercise.objects.get(gym=coach.gym, key="sn"), athlete)
    return day.sessions.get()


def test_form_video_upload_and_review(page: Page, base, athlete, coach, todays_session, sign_in, tmp_path):
    clip = tmp_path / "snatch.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 50_000)  # the bucket doesn't care what's inside
    log = sessions.start(athlete, todays_session)
    sign_in(page, athlete.user)
    page.goto(base + f"/app/log/{log.pk}/exercise/1/")
    page.get_by_label("Add a form video for Dana").set_input_files(str(clip))
    expect(page.locator("#toastStack")).to_contain_text("Video sent — Dana will review it")
    card = page.locator(f"#videos-{log.exercises.get().pk}")
    expect(card).to_contain_text("Dana will review it")
    htmx_idle(page)
    card.get_by_label("Note for Dana").fill("Is the bar drifting forward?")
    card.get_by_label("Note for Dana").press("Tab")
    expect(page.locator("#toastStack")).to_contain_text("Note saved")
    video = FormVideo.objects.get()
    assert video.uploaded_at and video.size == clip.stat().st_size

    # The coach watches it in the page and replies.
    sign_in(page, coach.user)
    page.goto(base + "/coach/")
    page.locator("#attnCard a.attn", has_text="Uploaded a form video: Snatch").click()
    note = page.locator(f"#video-{video.pk}")
    expect(note).to_be_in_viewport()
    htmx_idle(page)
    note.get_by_role("button", name="Review").click()
    modal = page.locator(".modal.open")
    expect(modal.locator("video")).to_be_visible()
    assert "X-Amz-Signature" in modal.locator("video").get_attribute("src")
    modal.get_by_label("Feedback for Maya").fill("Keep your lats on off the floor.")
    modal.get_by_role("button", name="Send & mark reviewed").click()
    expect(page.locator(f"#video-{video.pk}")).to_contain_text("reviewed")
    assert Message.objects.get().body.endswith("Keep your lats on off the floor.")


def _violations(page):
    page.add_script_tag(content=AXE)
    return page.evaluate(
        """async () => (await axe.run(
            // The sidebar stays put while the page scrolls; axe then measures its label
            // against the page instead of the dark sidebar (it's 7:1 there).
            {exclude: [['.who']]},
            {runOnly: ['wcag2a', 'wcag2aa', 'best-practice']},
        )).violations.map(v => v.id + ': ' + v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(' | '))"""
    )


def test_main_pages_pass_accessibility_checks(page: Page, base, athlete, coach, todays_session, sign_in):
    log = sessions.start(athlete, todays_session)
    sign_in(page, coach.user)
    problems = {}
    for url in [
        "/coach/",
        "/coach/athletes/",
        f"/coach/athletes/{athlete.pk}/overview/",
        f"/coach/athletes/{athlete.pk}/program/",
        f"/coach/athletes/{athlete.pk}/sessions/",
        f"/coach/athletes/{athlete.pk}/metrics/",
        f"/coach/athletes/{athlete.pk}/messages/",
        "/coach/programming/templates/",
        "/coach/programming/exercises/",
        "/coach/settings/",
    ]:
        page.goto(base + url)
        problems[url] = _violations(page)
    sign_in(page, athlete.user)
    page.set_viewport_size({"width": 420, "height": 900})
    for url in ["/app/", "/app/progress/", "/app/profile/", "/app/coach/", f"/app/log/{log.pk}/exercise/1/"]:
        page.goto(base + url)
        problems[url] = _violations(page)
    page.context.clear_cookies()
    page.goto(base + "/accounts/login/")
    problems["/accounts/login/"] = _violations(page)
    found = {url: v for url, v in problems.items() if v}
    assert not found, "\n".join(f"{url}: {v}" for url, v in found.items())


def test_install_card_follows_the_device(page: Page, base, athlete, sign_in, browser):
    sign_in(page, athlete.user)
    page.goto(base + "/app/")
    expect(page.locator("#installCard")).to_be_hidden()  # desktop Chrome: nothing to offer yet
    iphone = browser.new_context(
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    )
    phone = iphone.new_page()
    phone.context.add_cookies(page.context.cookies())
    phone.goto(base + "/app/")
    card = phone.locator("#installCard")
    expect(card).to_be_visible()
    expect(card.locator("[data-ios]")).to_be_visible()
    expect(card.get_by_role("button", name="Install the app")).to_be_hidden()
    card.get_by_role("button", name="Don't show this again").click()
    expect(card).to_be_hidden()
    phone.reload()
    expect(phone.locator("#installCard")).to_be_hidden()  # remembered
    iphone.close()
