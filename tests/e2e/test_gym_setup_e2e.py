import re

import pytest
from playwright.sync_api import Page, expect

from apps.accounts.models import Gym
from apps.exercises.models import Category, Exercise
from apps.programs.models import WeekType

from ..conftest import PASSWORD
from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)


def test_signup_with_general_strength(page: Page, base):
    page.goto(base + "/accounts/signup/")
    page.get_by_label("Name", exact=True).fill("Sam Trainer")
    page.get_by_label("Email").fill("sam@example.com")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_label("Gym or team name").fill("Sam's Strength")
    page.get_by_role("button", name="Create gym").click()
    expect(page.locator(".errorlist")).to_contain_text("Pick how you'd like to start.")
    page.get_by_label("Password").fill(PASSWORD)  # password fields are never re-filled
    page.locator("label.role-btn", has_text="General strength").click()
    page.get_by_role("button", name="Create gym").click()
    expect(page).to_have_url(base + "/coach/")
    page.locator(".snav a.navitem", has_text="Programming").click()
    expect(page).to_have_url(base + "/coach/programming/templates/")
    page.locator(".tabs a", has_text="Exercises").click()
    expect(page.locator("#exlibResults")).to_contain_text("Bench Press")
    expect(page.locator("#exlibFilters")).to_contain_text("upper-body")
    assert Gym.objects.get(name="Sam's Strength").week_types.count() == 5


def test_delete_a_category_by_moving_its_exercises(page: Page, base, coach, sign_in):
    sign_in(page, coach.user)
    page.goto(base + "/coach/programming/exercises/")
    page.get_by_role("link", name="Categories & tags").click()
    expect(page).to_have_url(base + "/coach/programming/exercises/organise/")
    page.get_by_role("button", name="Delete category Press").click()
    modal = page.locator(".modal.open")
    expect(modal).to_contain_text("2 exercises are in this category")
    modal.get_by_label("Move exercises to").select_option(label="Accessory")
    modal.get_by_role("button", name="Move and delete").click()
    expect(page.locator(".modal.open")).to_have_count(0)
    expect(page.locator("#toastStack")).to_contain_text("Moved 2 exercises to Accessory and deleted Press")
    expect(page.locator("#categoriesCard")).not_to_contain_text("Press")
    htmx_idle(page)
    assert not Category.objects.filter(gym=coach.gym, name="Press").exists()
    assert Exercise.objects.get(gym=coach.gym, name="Push Press").category.name == "Accessory"

    # Rename a category then move it immediately: the rename is kept.
    name = page.get_by_label("Category name: Squat")
    name.fill("Squats")
    page.get_by_role("button", name="Move Squat up").click()
    expect(page.get_by_label("Category name: Squats")).to_be_visible()


def test_edit_week_types_in_settings(page: Page, base, coach, sign_in):
    sign_in(page, coach.user)
    page.goto(base + "/coach/settings/")
    card = page.locator("#weekTypes")
    card.get_by_label("New week type name").fill("Peaking")
    card.get_by_role("button", name="Add").click()
    expect(page.locator("#toastStack")).to_contain_text("Week type “Peaking” added")
    htmx_idle(page)
    peaking = WeekType.objects.get(gym=coach.gym, name="Peaking")

    card.get_by_label("Description of Peaking").fill("Openers and singles")
    card.get_by_label("Description of Peaking").press("Tab")
    expect(page.locator("#toastStack .toast").last).to_contain_text("Week type saved")
    page.evaluate(f"""() => {{
        const input = document.querySelector('input[name="colour_{peaking.pk}"]');
        input.value = '#112233'; input.dispatchEvent(new Event('change', {{bubbles: true}}));
    }}""")
    expect(page.locator(f"#wtPill-{peaking.pk}")).to_have_attribute("style", re.compile("#112233"))
    peaking.refresh_from_db()
    assert (peaking.description, peaking.colour) == ("Openers and singles", "#112233")

    page.once("dialog", lambda d: d.accept())
    card.get_by_role("button", name="Remove week type Peaking").click()
    expect(page.locator("#toastStack")).to_contain_text("Deleted “Peaking”")
    assert not WeekType.objects.filter(pk=peaking.pk).exists()
