import pytest
from playwright.sync_api import Page, expect

from apps.programs.models import Prescription, Program

from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)


def add(page, day_index, name):
    page.locator(".day-col").nth(day_index).locator(".day-add").click()
    page.locator("#railSearch").fill(name)
    expect(page.locator("#libList")).to_contain_text(name)
    htmx_idle(page)
    page.get_by_role("button", name=f"Add {name} to the selected day", exact=True).click()
    htmx_idle(page)


def test_build_a_week_in_the_editor(page: Page, base, coach, athlete, sign_in):
    sign_in(page, coach.user)
    page.goto(base + f"/coach/athletes/{athlete.pk}/program/")
    page.get_by_label("Block name").fill("Comp Prep Block")
    page.get_by_label("Weeks").fill("3")
    page.get_by_role("button", name="Start program").click()
    expect(page.locator(".month-strip .wk-tab")).to_have_count(4)  # 3 weeks + "Add a week"
    expect(page.locator("#toastStack")).to_contain_text("Started “Comp Prep Block” with 3 weeks")

    # Tag chips in the rail filter the list.
    htmx_idle(page)
    page.locator("#railFilters label.tagchip", has_text="speed").click()
    expect(page.locator("#libList")).to_contain_text("Power Snatch")
    expect(page.locator("#libList")).not_to_contain_text("Back Squat")
    page.locator("#railFilters label.tagchip", has_text="speed").click()
    expect(page.locator("#libList")).to_contain_text("Back Squat")

    # Without a selected day, adding explains what to do.
    page.locator("#railSearch").fill("Snatch")
    htmx_idle(page)
    page.get_by_role("button", name="Add Snatch to the selected day", exact=True).click()
    expect(page.locator("#toastStack")).to_contain_text("Click a day on the board first")

    add(page, 0, "Snatch")
    add(page, 0, "Back Squat")
    add(page, 1, "Clean & Jerk")
    expect(page.locator(".day-col").nth(0).locator(".rx-item")).to_have_count(2)

    # Edit in the modal: % load, custom field, vary by set.
    page.locator(".day-col").nth(0).locator(".rx-item", has_text="Snatch").click()
    modal = page.locator(".modal.open")
    expect(modal).to_contain_text("Snatch —")
    htmx_idle(page)
    modal.get_by_label("Sets").fill("3")
    modal.get_by_label("Reps", exact=True).fill("2")
    modal.get_by_label("Load basis").select_option("percent")
    modal.locator("#id_load_value").fill("75")
    modal.get_by_role("button", name="+ add field").click()
    modal.get_by_label("Custom field 1 name").fill("Rest")
    modal.get_by_label("Custom field 1 value").fill("3 min")
    modal.get_by_label("Vary by set").check()
    modal.get_by_label("Load for set 3").fill("80")
    modal.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".modal.open")).to_have_count(0)
    snatch = page.locator(".day-col").nth(0).locator(".rx-item", has_text="Snatch")
    expect(snatch).to_contain_text("3 sets: 2@75%, 2@75%, 2@80% · Rest 3 min")

    # Drag Clean & Jerk from Tuesday to Thursday.
    page.locator(".day-col").nth(1).locator(".rx-item").first.drag_to(
        page.locator(".day-col").nth(3).locator("[data-rx-list]").first
    )
    expect(page.locator(".day-col").nth(3)).to_contain_text("Clean & Jerk")
    htmx_idle(page)
    assert Prescription.objects.get(exercise__name="Clean & Jerk").session.day.date.weekday() == 3

    # Publish, then duplicate: the copy is a draft and later weeks move back.
    page.get_by_role("button", name="Publish to Maya").click()
    expect(page.locator(".month-strip .wk-tab").first).to_contain_text("live")
    htmx_idle(page)
    page.get_by_role("button", name="Duplicate week").click()
    expect(page.locator(".month-strip .wk-tab")).to_have_count(5)
    expect(page.locator("#programEditor")).to_contain_text("Draft — not visible to Maya")
    htmx_idle(page)

    # Start a new program: the old one is ended and kept.
    page.get_by_role("button", name="Start a new program").click()
    modal = page.locator(".modal.open")
    expect(modal).to_contain_text("Starting a new program ends the current one")
    modal.get_by_label("Block name").fill("Next Block")
    modal.get_by_label("Weeks").fill("2")
    modal.get_by_role("button", name="Start program").click()
    expect(page.locator("#programEditor")).to_contain_text("Next Block")
    assert Program.objects.filter(athlete=athlete).count() == 2
    assert Program.objects.get(athlete=athlete, active=True).name == "Next Block"
