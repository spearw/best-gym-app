import re

import pytest
from playwright.sync_api import Page, expect

from apps.accounts.models import MaxEntry
from apps.exercises.models import Exercise
from apps.workouts.models import CheckinQuestion, copy_defaults_to, install_default_questions

from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)


def test_exercise_library_search_filter_create_archive(page: Page, base, coach, sign_in):
    sign_in(page, coach.user)
    page.goto(base + "/coach/")
    page.locator(".snav a.navitem", has_text="Programming").click()
    expect(page).to_have_url(base + "/coach/programming/templates/")  # the mockup opens on Templates
    page.locator(".tabs a", has_text="Exercises").click()
    expect(page).to_have_url(base + "/coach/programming/exercises/")
    expect(page.locator("#exlibResults")).to_contain_text("24 exercises")
    htmx_idle(page)  # the page was just swapped in; let HTMX wire it up before typing

    page.get_by_label("Search exercises").fill("squat")
    expect(page.locator("#exlibResults")).to_contain_text("Front Squat")
    expect(page.locator("#exlibResults")).not_to_contain_text("Power Clean")
    expect(page).to_have_url(re.compile(r"q=squat"))  # filters survive a reload
    page.get_by_label("Search exercises").fill("")
    page.locator("#exlibFilters label.tagchip", has_text="overhead").click()
    page.locator("#exlibFilters label.tagchip", has_text="strength").click()
    expect(page.locator("#exlibResults")).to_contain_text("2 exercises matching")
    htmx_idle(page)

    page.get_by_role("button", name="+ New exercise").click()
    modal = page.locator(".modal.open")
    modal.get_by_label("Name").fill("Behind-the-neck Jerk")
    modal.get_by_label("Category").select_option(label="Clean & Jerk")
    modal.get_by_label("Percentages worked from").select_option(label="Clean & Jerk")
    modal.locator("label.tagchip", has_text="overhead").click()
    modal.locator("label.tagchip", has_text="strength").click()
    modal.get_by_role("button", name="Save exercise").click()
    expect(page.locator(".modal.open")).to_have_count(0)
    expect(page.locator("#toastStack")).to_contain_text("“Behind-the-neck Jerk” added to the library")
    expect(page.locator("#exlibResults")).to_contain_text(
        "Behind-the-neck Jerk"
    )  # list refreshed, filters kept
    htmx_idle(page)  # the list was just redrawn; let HTMX wire up its buttons before clicking

    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Archive Behind-the-neck Jerk").click()
    expect(page.locator("#exlibResults")).not_to_contain_text("Behind-the-neck Jerk")
    assert Exercise.objects.get(name="Behind-the-neck Jerk").archived


def test_coach_fills_a_skipped_metric(page: Page, base, coach, athlete, sign_in):
    sign_in(page, coach.user)
    page.goto(base + "/coach/athletes/")
    page.locator("#clientCards a", has_text="Maya Torres").click()
    expect(page).to_have_url(base + f"/coach/athletes/{athlete.pk}/metrics/")
    expect(page.locator(".metric.missing")).to_have_count(6)
    expect(page.locator("#cdStats")).to_contain_text("—")

    page.get_by_role("button", name="Edit Snatch 1RM").click()
    modal = page.locator(".modal.open")
    modal.get_by_label("Value (kg)").fill("82.5")
    modal.get_by_role("button", name="Save").click()
    expect(page.locator(".modal.open")).to_have_count(0)
    expect(page.locator(".metric.missing")).to_have_count(5)
    expect(page.locator("#cdStats")).to_contain_text("82.5 kg")  # header updated out of band
    expect(page.locator("#metricsPanel")).to_contain_text("Recent measurements")
    assert MaxEntry.objects.get(athlete=athlete).source == "coach"

    page.locator(".tabs").get_by_role("link", name="Program", exact=True).click()
    expect(page.locator(".tabs a.active")).to_have_text("Program")
    expect(page.locator("#coach-main")).to_contain_text("Start a program for Maya")


def test_question_builder_edits_an_athletes_copy(page: Page, base, coach, athlete, sign_in):
    install_default_questions(coach.gym)
    copy_defaults_to(athlete)
    sign_in(page, coach.user)
    page.goto(base + f"/coach/athletes/{athlete.pk}/metrics/")
    builder = page.locator("#qBuilder")
    expect(builder.locator(".q-row")).to_have_count(2)

    builder.get_by_label("New option").fill("Travelling")
    builder.get_by_label("New option").press("Enter")
    expect(builder).to_contain_text("Travelling")
    expect(page.locator("#toastStack")).to_contain_text("live from Maya's next session")
    htmx_idle(page)

    wording = builder.get_by_label("Question 1 wording")
    wording.fill("How ready do you feel?")
    wording.press("Tab")  # the change event saves...
    builder.get_by_role(
        "button", name="Move down"
    ).first.click()  # ...and an immediate move is queued behind it
    expect(builder.get_by_label("Question 2 wording")).to_have_value("How ready do you feel?")

    texts = list(CheckinQuestion.objects.for_athlete(athlete).active().values_list("text", flat=True))
    assert texts == ["Anything affecting today's session?", "How ready do you feel?"]
    defaults = CheckinQuestion.objects.gym_defaults(coach.gym).active()
    assert defaults.first().text == "How recovered do you feel today?"  # defaults untouched


def test_tracked_lifts_then_archive_and_delete(page: Page, base, coach, athlete, sign_in):
    from apps.exercises.models import TrackedLift

    snatch = Exercise.objects.get(gym=coach.gym, key="sn")
    MaxEntry.objects.create(athlete=athlete, exercise=snatch, date="2026-09-01", kg=80, source="coach")
    sign_in(page, coach.user)

    # Settings: track Front Squat, move it to the top.
    page.goto(base + "/coach/settings/")
    card = page.locator("#trackedLifts")
    expect(card).to_contain_text("3 of 6")
    card.get_by_label("Lift to track").select_option(label="Front Squat")
    card.get_by_role("button", name="Track", exact=True).click()
    expect(card).to_contain_text("4 of 6")
    htmx_idle(page)
    for _ in range(3):
        card.get_by_role("button", name="Move Front Squat up").click()
        htmx_idle(page)
    expect(card.locator(".spread b").first).to_have_text("Front Squat")

    # The athlete's Metrics tab follows the new list.
    page.goto(base + f"/coach/athletes/{athlete.pk}/metrics/")
    expect(page.locator(".metric .l").nth(2)).to_have_text("Front Squat 1RM")

    # Archive the snatch: warned that it's tracked, and it's untracked.
    page.goto(base + "/coach/programming/exercises/?q=snatch")
    dialog_text = []
    page.once("dialog", lambda d: (dialog_text.append(d.message), d.accept()))
    page.get_by_role("button", name="Archive Snatch", exact=True).click()
    expect(page.locator("#toastStack")).to_contain_text("removed from tracked lifts")
    assert "also a tracked lift" in dialog_text[0]
    assert not TrackedLift.objects.filter(exercise=snatch).exists()

    # Delete it for good from the archived list, after reading the impact.
    page.get_by_label("Show archived").check()
    page.get_by_role("button", name="Delete…").click()
    modal = page.locator(".modal.open")
    expect(modal).to_contain_text("1 max entry from the history of Maya Torres")
    expect(modal).to_contain_text("Power Snatch")
    modal.get_by_role("button", name="Delete permanently").click()
    expect(page.locator(".modal.open")).to_have_count(0)
    expect(page.locator("#toastStack")).to_contain_text("“Snatch” deleted along with 1 max entry")
    expect(page.locator("#exlibResults")).to_contain_text("No archived exercises")
    assert not Exercise.objects.filter(pk=snatch.pk).exists()
