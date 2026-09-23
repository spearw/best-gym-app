"""Dragging on the program board: whole-column drop areas, dragging from the library,
the drop-target highlight, and the library drawer on narrow screens."""

import datetime

import pytest
from playwright.sync_api import Page, expect

from apps.exercises.models import Exercise
from apps.programs import services
from apps.programs.models import Prescription, WeekType

from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)
MON = datetime.date(2026, 9, 21)


@pytest.fixture
def program(athlete, coach):
    return services.start_program(
        athlete, "Block", MON, 2, WeekType.objects.get(gym=coach.gym, name="Accumulation"), by=coach.user
    )


def ex(gym, key):
    return Exercise.objects.get(gym=gym, key=key)


def drag(page, source, x, y, check_highlight_on=None):
    """Press on `source`, move in steps to (x, y), release. Sortable needs real mouse moves."""
    box = source.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 5, box["y"] + box["height"] / 2 + 5, steps=3)
    page.mouse.move(x, y, steps=15)
    if check_highlight_on is not None:
        expect(check_highlight_on).to_have_class(__import__("re").compile(r"\bdroptarget\b"))
    page.mouse.up()
    htmx_idle(page)


def bottom_of(locator):
    box = locator.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] - 60


def search_library(page, name):
    """Search the rail and wait for this search's result (the search runs 200 ms after typing,
    so a count check alone can match the previous search's list)."""
    page.locator("#railSearch").fill(name)
    expect(page.locator("#libList .lib-item")).to_have_count(1)
    expect(page.locator("#libList .lib-item").first).to_contain_text(name)
    htmx_idle(page)


def keys_on(day):
    return list(
        Prescription.objects.filter(session__day=day)
        .order_by("order")
        .values_list("exercise__key", flat=True)
    )


def test_drop_anywhere_in_a_day_including_an_empty_week(page: Page, base, coach, athlete, program, sign_in):
    week1, week2 = program.weeks.all()
    mon = week1.days.first()
    services.add_prescription(mon, ex(coach.gym, "sn"), athlete)
    services.add_prescription(mon, ex(coach.gym, "bsq"), athlete)
    tue = list(week1.days.all())[1]
    services.add_prescription(tue, ex(coach.gym, "cj"), athlete)
    sign_in(page, coach.user)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(base + f"/coach/athletes/{athlete.pk}/program/?week={week1.pk}")
    cols = page.locator(".day-col")

    # Drop Clean & Jerk into the empty lower part of Monday, well below its cards: it goes last.
    x, y = bottom_of(cols.nth(0))
    drag(page, cols.nth(1).locator(".rx-item").first, x, y, check_highlight_on=cols.nth(0))
    assert keys_on(mon) == ["sn", "bsq", "cj"]
    expect(page.locator(".day-col.droptarget")).to_have_count(0)  # highlight cleared

    # In an empty week, drop near the bottom of Thursday, far from the day name.
    page.goto(base + f"/coach/athletes/{athlete.pk}/program/?week={week2.pk}")
    htmx_idle(page)
    x, y = bottom_of(cols.nth(3))
    search_library(page, "Snatch Pull")
    drag(page, page.locator("#libList .lib-item").first, x, y, check_highlight_on=cols.nth(3))
    thursday = list(week2.days.all())[3]
    assert keys_on(thursday) == ["snp"]
    expect(cols.nth(3)).to_contain_text("Snatch Pull")


def test_drag_from_the_library_to_a_position(page: Page, base, coach, athlete, program, sign_in):
    mon = program.weeks.first().days.first()
    services.add_prescription(mon, ex(coach.gym, "sn"), athlete)
    services.add_prescription(mon, ex(coach.gym, "bsq"), athlete)
    sign_in(page, coach.user)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(base + f"/coach/athletes/{athlete.pk}/program/?week={program.weeks.first().pk}")
    search_library(page, "Snatch Pull")
    squat = page.locator(".day-col").nth(0).locator(".rx-item", has_text="Back Squat")
    box = squat.bounding_box()
    drag(page, page.locator("#libList .lib-item").first, box["x"] + box["width"] / 2, box["y"] + 6)
    assert keys_on(mon) == ["sn", "snp", "bsq"]  # landed between the two
    expect(page.locator("#libList")).to_contain_text("Snatch Pull")  # the library keeps its copy
    expect(page.locator("#toastStack")).to_contain_text("Snatch Pull → Mon 21 Sep")


def test_library_drawer_on_narrow_screens(page: Page, base, coach, athlete, program, sign_in):
    sign_in(page, coach.user)
    page.set_viewport_size({"width": 1000, "height": 800})
    page.goto(base + f"/coach/athletes/{athlete.pk}/program/?week={program.weeks.first().pk}")
    rail = page.locator(".lib-rail")
    expect(rail).to_be_hidden()
    page.get_by_role("button", name="Exercise library").click()
    expect(rail).to_be_visible()
    expect(rail).to_have_class(__import__("re").compile(r"\bopen\b"))

    # Pick a day, then + in the drawer.
    page.locator(".day-col").nth(0).locator(".day-add").click()
    search_library(page, "Back Squat")
    page.get_by_role("button", name="Add Back Squat to the selected day").click()
    htmx_idle(page)
    expect(page.locator(".day-col").nth(0)).to_contain_text("Back Squat")

    # Drag from the drawer onto a day the drawer doesn't cover.
    search_library(page, "Front Squat")
    x, y = bottom_of(page.locator(".day-col").nth(1))
    drag(page, page.locator("#libList .lib-item").first, x, y)
    expect(page.locator(".day-col").nth(1)).to_contain_text("Front Squat")

    page.keyboard.press("Escape")
    expect(rail).to_be_hidden()


def test_wide_screens_show_the_library_without_a_button(page: Page, base, coach, athlete, program, sign_in):
    sign_in(page, coach.user)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(base + f"/coach/athletes/{athlete.pk}/program/")
    expect(page.locator(".lib-rail")).to_be_visible()
    expect(page.get_by_role("button", name="Exercise library")).to_be_hidden()
    rail_right = page.evaluate("document.querySelector('.lib-rail').getBoundingClientRect().right")
    assert rail_right <= 1440
