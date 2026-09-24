"""Build a template in the editor, then preview and apply it on an athlete's board."""

from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from apps.library.models import Template, TemplateSlot
from apps.programs.models import Prescription

from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)


def test_build_and_apply_a_template(page: Page, base, coach, athlete, sign_in):
    sign_in(page, coach.user)
    page.goto(base + "/coach/programming/templates/")
    expect(page.locator("body")).to_contain_text("No templates yet")
    page.get_by_role("button", name="+ New template").click()
    expect(page.locator(".tpl-week")).to_have_count(1)
    expect(page.locator(".tpl-sess")).to_have_count(3)
    htmx_idle(page)
    page.get_by_label("Template name").fill("Squat Block")
    page.get_by_label("Template name").press("Tab")
    htmx_idle(page)

    # Select session A and add a fixed exercise from the rail.
    page.locator(".tpl-sess").nth(0).click()
    page.locator("#railSearch").fill("Back Squat")
    expect(page.locator("#libList .lib-item")).to_have_count(1)
    htmx_idle(page)
    page.get_by_role("button", name="Add Back Squat to the selected session").click()
    expect(page.locator(".tpl-sess").nth(0).locator(".rx-item")).to_have_count(1)
    expect(page.locator("#toastStack")).to_contain_text("Back Squat → Session A")

    # A tag slot in session B from the ticked tags.
    page.locator("#railSearch").fill("")
    htmx_idle(page)
    page.locator(".tpl-sess").nth(1).click()
    page.locator("#railFilters label.tagchip", has_text="unilateral").click()
    expect(page.get_by_role("button", name="+ Tag slot (1 qualify)")).to_be_enabled()
    htmx_idle(page)
    page.get_by_role("button", name="+ Tag slot (1 qualify)").click()
    expect(page.locator(".tpl-sess").nth(1).locator(".rx-item.tagslot")).to_contain_text("Tag slot")

    # Edit the squat's dose in the slot modal.
    htmx_idle(page)
    page.locator(".tpl-sess").nth(0).locator(".rx-item").click()
    modal = page.locator(".modal.open")
    expect(modal).to_contain_text("Slot type")
    htmx_idle(page)
    modal.get_by_label("Sets").fill("5")
    modal.get_by_label("Reps", exact=True).fill("5")
    modal.get_by_label("Load basis").select_option("percent")
    modal.locator("#id_load_value").fill("70")
    modal.get_by_role("button", name="Save").click()
    expect(page.locator(".modal.open")).to_have_count(0)
    expect(page.locator(".tpl-sess").nth(0)).to_contain_text("5×5 @ 70%")

    # A progressive second week: a copy, 2.5 points heavier.
    htmx_idle(page)
    page.get_by_label("Percentage points to add to every % load").fill("2.5")
    page.get_by_role("button", name="+ Add week").click()
    expect(page.locator(".tpl-week")).to_have_count(2)
    expect(page.locator(".tpl-week").nth(1)).to_contain_text("5×5 @ 72.5%")
    template = Template.objects.get(name="Squat Block")
    assert TemplateSlot.objects.filter(session__week__template=template, exercise__key="bsq").count() == 2

    # Apply it to Maya: preview on her board, change the days, confirm.
    page.get_by_role("button", name="Apply to athlete").click()
    modal = page.locator(".modal.open")
    modal.get_by_label("Athlete").select_option(str(athlete.pk))
    modal.get_by_role("button", name="Preview on their board →").click()
    expect(page.locator(".apply-bar")).to_contain_text("Previewing")
    expect(page.locator(".apply-bar")).to_contain_text("2 new weeks")
    expect(page.locator(".wk-tab.ghost")).to_have_count(2)
    expect(page.locator(".week-board.ghost")).to_contain_text("Back Squat")
    htmx_idle(page)
    page.locator(".apply-bar .daypick-day", has_text="Wed").click()  # 3 days → 2 days a week
    expect(page.locator(".apply-bar")).to_contain_text("3 new weeks")
    htmx_idle(page)
    page.get_by_role("button", name="Confirm apply").click()
    expect(page.locator("#toastStack")).to_contain_text("“Squat Block” applied — 3 weeks")
    expect(page.locator(".apply-bar")).to_have_count(0)
    expect(page.locator(".week-board")).to_contain_text("Back Squat")
    program = athlete.programs.get()
    assert program.weeks.count() == 3 and not program.weeks.filter(published=True).exists()
    rx = Prescription.objects.filter(session__day__week__program=program, exercise__key="bsq").first()
    assert (rx.sets, rx.load_value) == (5, Decimal("70.00"))
