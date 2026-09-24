"""Undo on the board, habits from coach to athlete, and the Overview charts."""

import pytest
from playwright.sync_api import Page, expect

from apps.programs import services as program_services
from apps.programs.models import Prescription, WeekType

from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def program(athlete, coach):
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    program = program_services.start_program(athlete, "Block", athlete.today(), 1, week_type, by=coach.user)
    program_services.set_published(program.weeks.get(), True)
    return program


def add(page, day_index, name):
    page.locator(".day-col").nth(day_index).locator(".day-add").click()
    page.locator("#railSearch").fill(name)
    expect(page.locator("#libList")).to_contain_text(name)
    htmx_idle(page)
    page.get_by_role("button", name=f"Add {name} to the selected day", exact=True).click()
    htmx_idle(page)


def test_undo_and_habits(page: Page, base, coach, athlete, program, sign_in):
    sign_in(page, coach.user)
    page.goto(base + f"/coach/athletes/{athlete.pk}/program/")
    undo = page.locator("#undoBtn")
    expect(undo).to_be_disabled()
    add(page, 0, "Snatch")
    add(page, 0, "Back Squat")
    expect(undo).to_have_text("Undo: Add Back Squat")
    undo.click()
    expect(page.locator("#toastStack")).to_contain_text("Undone: Add Back Squat")
    expect(page.locator(".day-col").nth(0).locator(".rx-item")).to_have_count(1)
    htmx_idle(page)
    page.locator("body").press("Control+z")  # the keyboard shortcut
    expect(page.locator(".day-col").nth(0).locator(".rx-item")).to_have_count(0)
    assert not Prescription.objects.exists()

    # Prescribe a habit on the Program tab.
    card = page.locator("#habitCard")
    card.get_by_label("Habit name").fill("Sleep 8 hours")
    card.get_by_label("Icon").select_option("😴")
    card.get_by_role("button", name="+ Prescribe habit").click()
    expect(page.locator("#habitCard")).to_contain_text("Sleep 8 hours")
    expect(page.locator("#habitCard")).to_contain_text("Every day · streak 0")

    # The athlete ticks it off, and can fill in yesterday.
    sign_in(page, athlete.user)
    page.goto(base + "/app/")
    habits = page.locator("#mHabits")
    expect(habits).to_contain_text("Today's habits")
    expect(habits).to_contain_text("0/1 done")
    habits.locator(".habit-row", has_text="Sleep 8 hours").click()
    expect(page.locator("#mHabits")).to_contain_text("1/1 done")
    expect(page.locator("#mHabits .habit-row.done")).to_have_count(1)
    htmx_idle(page)
    page.get_by_role("button", name="Forgot yesterday?").click()
    expect(page.locator("#mHabits")).to_contain_text("Yesterday's habits")
    htmx_idle(page)
    page.locator("#mHabits .habit-row", has_text="Sleep 8 hours").click()
    expect(page.locator("#mHabits .habit-row.done")).to_have_count(1)

    # The coach sees the streak.
    sign_in(page, coach.user)
    page.goto(base + f"/coach/athletes/{athlete.pk}/program/")
    expect(page.locator("#habitCard")).to_contain_text("streak 2 · done today")
    page.goto(base + f"/coach/athletes/{athlete.pk}/overview/")
    expect(page.locator("body")).to_contain_text("Estimated 1RM trend")
    expect(page.locator("body")).to_contain_text("Weekly volume & compliance")
