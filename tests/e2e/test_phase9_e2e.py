"""Phase 9 in a real browser: the coach marks a warm-up drill, a section and a superset
on the board; the athlete answers a short-answer check-in, ticks the warm-up (the drill's
name links to its YouTube demo) and logs a superset on one screen. Both new player
screens pass the accessibility check."""

import pytest
from playwright.sync_api import Page, expect

from apps.exercises.models import Exercise
from apps.programs import services as program_services
from apps.programs.models import WeekType
from apps.workouts.models import CheckinQuestion, QuestionType, SessionLog, SetLog

from .conftest import htmx_idle
from .test_phase8_e2e import _violations

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def board(athlete, coach):
    gym = coach.gym
    week_type = WeekType.objects.get(gym=gym, name="Accumulation")
    program = program_services.start_program(athlete, "Meso 1", athlete.today(), 1, week_type, by=coach.user)
    week = program.weeks.get()
    program_services.set_published(week, True)
    day = week.days.get(date=athlete.today())
    Exercise.objects.filter(gym=gym, key="mob").update(youtube_url="https://www.youtube.com/watch?v=demo1")
    for key in ("bsq", "rdl", "row", "mob"):
        program_services.add_prescription(day, Exercise.objects.get(gym=gym, key=key), athlete)
    CheckinQuestion.objects.for_athlete(athlete).delete()
    CheckinQuestion.objects.create(
        athlete=athlete, order=0, type=QuestionType.SCALE, text="Soreness level", detail_label="Where?"
    )
    CheckinQuestion.objects.create(athlete=athlete, order=1, type=QuestionType.TEXT, text="Other notes")
    return day


def edit(page, name):
    page.locator(".rx-item", has_text=name).first.click()
    modal = page.locator(".modal.open")
    expect(modal).to_contain_text(name)
    htmx_idle(page)
    return modal


def save(page):
    page.locator(".modal.open").get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".modal.open")).to_have_count(0)
    htmx_idle(page)


def test_coach_lays_out_a_session_and_athlete_trains_it(page: Page, base, athlete, coach, board, sign_in):
    sign_in(page, coach.user)
    page.goto(base + f"/coach/athletes/{athlete.pk}/program/")
    day = page.locator(".day-col.selected, .day-col").filter(has=page.locator(".rx-item")).first

    # The mobility drill becomes a warm-up: no sets or load, just a dose; it moves to the top.
    modal = edit(page, "T-spine + Ankle Mobility")
    modal.get_by_label("Warm-up drill").check()
    expect(modal.get_by_label("Sets")).to_be_hidden()
    modal.get_by_label("Dose").fill("x 5 breaths each side")
    save(page)
    expect(day.locator(".rx-head").first).to_have_text("Warm-up")
    expect(day.locator(".rx-item").first).to_contain_text("x 5 breaths each side")

    # A Strength section, an RIR range, and a Hypertrophy superset.
    modal = edit(page, "Back Squat")
    modal.get_by_label("RIR target").fill("1-2")
    modal.get_by_label("Section heading above this").fill("Strength")
    save(page)
    expect(day.locator(".rx-item", has_text="Back Squat")).to_contain_text("RIR 1–2")
    modal = edit(page, "Romanian Deadlift")
    modal.get_by_label("Reps", exact=True).fill("10-12")
    modal.get_by_label("Section heading above this").fill("Hypertrophy")
    modal.get_by_label("Section note").fill("Superset non-competing exercises")
    save(page)
    modal = edit(page, "Pendlay Row")
    modal.get_by_label("Superset with the exercise above").check()
    save(page)
    expect(day.locator(".rx-head", has_text="Hypertrophy")).to_contain_text(
        "Superset non-competing exercises"
    )
    expect(day.locator(".rx-item", has_text="Romanian Deadlift").locator(".ss")).to_have_text("B1")
    expect(day.locator(".rx-item", has_text="Pendlay Row").locator(".ss")).to_have_text("B2")
    page.get_by_role("button", name="Undo").click()  # undo covers layout edits too
    expect(day.locator(".ss")).to_have_count(0)
    modal = edit(page, "Pendlay Row")
    modal.get_by_label("Superset with the exercise above").check()
    save(page)
    expect(day.locator(".ss")).to_have_count(2)

    # The program note.
    page.locator("summary", has_text="Program note").click()
    page.get_by_label("Program note").fill("Rest as needed on all lifts.")
    page.get_by_label("Program note").press("Tab")
    expect(page.locator("#toastStack")).to_contain_text("Program note saved")

    # The athlete: week card, check-in with a follow-up box and a short answer.
    sign_in(page, athlete.user)
    page.set_viewport_size({"width": 420, "height": 900})
    page.goto(base + "/app/")
    card = page.locator(".today-card")
    expect(card).to_contain_text("Warm-up")
    expect(card).to_contain_text("B2 Pendlay Row")
    page.locator("summary", has_text="About Meso 1").click()
    expect(page.locator("body")).to_contain_text("Rest as needed on all lifts.")
    page.get_by_role("button", name="Start session →").click()
    page.get_by_role("button", name="6 of 10").click()
    page.get_by_label("Where?").fill("hamstrings")
    page.get_by_role("button", name="Continue").click()
    page.get_by_label("Other notes").fill("Slept badly")
    page.get_by_role("button", name="Continue").click()
    expect(page.locator(".mcard")).to_contain_text("6 / 10 · hamstrings")
    page.get_by_role("button", name="Start session →").click()

    # Warm-up checklist: the name opens the YouTube demo; tick it off.
    expect(page.locator("h1")).to_have_text("Warm-up")
    demo = page.get_by_role("link", name="T-spine + Ankle Mobility")
    expect(demo).to_have_attribute("href", "https://www.youtube.com/watch?v=demo1")
    expect(demo).to_have_attribute("target", "_blank")
    assert not _violations(page)
    page.get_by_role("button", name="Done: T-spine + Ankle Mobility").click()
    expect(page.locator(".wu-item.done")).to_have_count(1)
    page.get_by_role("link", name="Start lifting →").click()

    # Squat, then the superset on one screen.
    expect(page.locator(".player-section")).to_have_text("Strength")
    expect(page.locator(".rx-banner")).to_contain_text("RIR 1–2")
    page.get_by_role("link", name="Next exercise →").click()
    expect(page.locator("body")).to_contain_text("Superset — alternate between these")
    expect(page.get_by_label("B1 Set 1 reps", exact=True)).to_have_value("10")
    assert not _violations(page)
    page.get_by_role("button", name="Mark B1 set 1 done").click()
    page.get_by_role("button", name="Mark B2 set 1 done").click()
    page.wait_for_function(
        "() => [...document.querySelectorAll('.set-row')].every(r => r.dataset.state === 'saved')"
    )
    assert SetLog.objects.filter(done=True).count() == 2
    log = SessionLog.objects.get()
    assert log.exercises.get(warmup=True).checked_at is not None
    assert [a.value for a in log.answers.all()] == ["6", "Slept badly"]
