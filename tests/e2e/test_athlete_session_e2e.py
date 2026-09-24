"""The athlete's core flow in a real browser: week → check-in → player → post-session →
done, with each set saved as it's ticked (including while offline), then the coach's
Sessions tab showing what was asked for beside what was done."""

import datetime
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from apps.accounts.models import MaxEntry
from apps.exercises.models import Exercise
from apps.programs import services
from apps.programs.models import LoadBasis, ProgramDay, WeekType
from apps.workouts.models import IssueReport, SessionLog, SetLog, copy_defaults_to, install_default_questions

from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def todays_session(athlete, coach):
    gym = coach.gym
    install_default_questions(gym)
    copy_defaults_to(athlete)
    today = athlete.today()
    sn, bsq = (Exercise.objects.get(gym=gym, key=k) for k in ("sn", "bsq"))
    MaxEntry.objects.create(
        athlete=athlete, exercise=sn, date=today - datetime.timedelta(days=20), kg=100, source="coach"
    )
    program = services.start_program(
        athlete, "Comp Prep", today, 1, WeekType.objects.get(gym=gym, name="Accumulation"), by=coach.user
    )
    week = program.weeks.get()
    services.set_published(week, True)
    week.focus_note = "Openers Saturday."
    week.save()
    day = ProgramDay.objects.get(week=week, date=today)
    for exercise, sets, reps, basis, value in [
        (sn, 3, 2, LoadBasis.PERCENT, 80),
        (bsq, 2, 5, LoadBasis.WEIGHT, 100),
    ]:
        rx = services.add_prescription(day, exercise, athlete)
        rx.sets, rx.rep_scheme, rx.reps, rx.load_basis, rx.load_value = (
            sets,
            str(reps),
            reps,
            basis,
            Decimal(value),
        )
        rx.save()
    return day.sessions.get()


def rows(page):
    return page.locator(".set-row")


def wait_saved(page):
    """Every set row has reached the server (data-state is "saved")."""
    page.wait_for_function(
        "() => [...document.querySelectorAll('.set-row')].every(r => r.dataset.state === 'saved')"
    )


@pytest.mark.allow_browser_errors("ERR_INTERNET_DISCONNECTED")  # the offline part, on purpose
def test_athlete_logs_a_session(page: Page, base, athlete, coach, todays_session, sign_in):
    sign_in(page, athlete.user)
    page.goto(base + "/app/")
    expect(page.locator(".today-card")).to_contain_text("Today's session")
    expect(page.locator(".today-card")).to_contain_text("3×2 @ 80%")
    expect(page.locator("body")).to_contain_text("Openers Saturday.")
    page.get_by_role("button", name="Start session →").click()

    # Check-in: one question per step.
    expect(page.locator(".step-lbl")).to_have_text("1 of 3")
    expect(page.locator("#mTabbar")).to_be_hidden()
    continue_button = page.get_by_role("button", name="Continue")
    expect(continue_button).to_be_disabled()
    page.get_by_role("button", name="7 of 10").click()
    continue_button.click()
    expect(page.locator(".step-lbl")).to_have_text("2 of 3")
    page.get_by_role("button", name="Legs are sore").click()
    page.get_by_role("button", name="Continue").click()
    expect(page.locator("body")).to_contain_text("Check-in complete")
    expect(page.locator(".mcard")).to_contain_text("7 / 10")
    page.get_by_role("button", name="Start session →").click()

    # Player: snatch, loads suggested from the 100 kg max.
    expect(page.locator(".player-head h1")).to_have_text("Snatch")
    expect(page.locator(".rx-banner")).to_contain_text("≈ 80 kg from your Snatch max")
    expect(rows(page)).to_have_count(3)
    expect(rows(page).nth(0).get_by_label("Set 1 load in kg")).to_have_value("80")
    rows(page).nth(0).get_by_role("button", name="Mark set 1 done").click()
    rows(page).nth(1).get_by_role("button", name="Mark set 2 done").click()
    expect(rows(page).nth(1)).to_have_class("set-row done")
    wait_saved(page)

    # A set ticked while offline stays marked unsaved, then saves itself on reconnecting.
    page.context.set_offline(True)
    rows(page).nth(2).get_by_label("Set 3 load in kg").fill("82.5")
    rows(page).nth(2).get_by_label("Set 3 reps", exact=True).fill("2")
    rows(page).nth(2).get_by_role("button", name="Mark set 3 done").click()
    expect(rows(page).nth(2)).to_have_class("set-row done unsaved")
    expect(page.locator("#toastStack")).to_contain_text("Couldn't save set 3")
    page.context.set_offline(False)
    page.evaluate("window.dispatchEvent(new Event('online'))")
    wait_saved(page)
    assert SetLog.objects.filter(done=True).count() == 3
    assert SetLog.objects.get(set_number=3).load_kg == Decimal("82.50")

    page.get_by_role("link", name="Next exercise →").click()
    expect(page.locator(".player-head h1")).to_have_text("Back Squat")
    rows(page).nth(0).get_by_role("button", name="Mark set 1 done").click()
    wait_saved(page)
    page.get_by_role("link", name="Finish session →").click()

    # Post-session: RPE, a note, and an issue report.
    finish = page.get_by_role("button", name="Finish & save")
    expect(finish).to_be_disabled()
    page.get_by_role("button", name="RPE 8").click()
    page.get_by_label("Notes for").fill("Snatches felt quick")
    page.get_by_role("button", name="Report an issue or pain").click()
    modal = page.locator(".modal.open")
    modal.get_by_label("Where / what?").fill("Left wrist at lockout")
    htmx_idle(page)
    modal.get_by_role("button", name="Send to Dana").click()
    expect(page.locator("#issueList")).to_contain_text("Left wrist at lockout")
    expect(page.locator(".modal.open")).to_have_count(0)
    finish.click()

    expect(page.locator(".done-hero")).to_contain_text("Session complete")
    expect(page.locator(".done-stats")).to_contain_text("4/5")
    log = SessionLog.objects.get()
    assert log.finished and log.session_rpe == 8 and log.comment == "Snatches felt quick"
    assert [a.value for a in log.answers.all()] == ["7", "Legs are sore"]
    assert IssueReport.objects.get().session_log == log

    page.get_by_role("link", name="Back to my week").click()
    expect(page.locator(".today-card")).to_contain_text("Completed ✓")
    expect(page.locator(".ws-day.today")).to_contain_text("✓")

    # The coach sees what was asked for beside what was done.
    sign_in(page, coach.user)
    page.goto(base + f"/coach/athletes/{athlete.pk}/sessions/")
    session = page.locator("details.sess").first
    expect(session).to_contain_text("asked 3×2 @ 80% (≈ 80 kg)")
    expect(session).to_contain_text("did 2×2 @ 80 kg, 1×2 @ 82.5 kg")
    expect(session).to_contain_text("Legs are sore")
    expect(session).to_contain_text("Left wrist at lockout")
    page.locator("#histFilter").fill("clean")
    expect(page.locator("#sessLog")).to_contain_text("No sessions with “clean”")
