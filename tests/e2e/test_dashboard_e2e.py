"""The coach's attention feed and coach–athlete messages in a real browser."""

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import htmx_idle

pytestmark = pytest.mark.django_db(transaction=True)


def test_message_round_trip_through_the_feed(page: Page, base, coach, athlete, sign_in):
    # The athlete writes to their coach.
    sign_in(page, athlete.user)
    page.goto(base + "/app/coach/")
    expect(page.locator("body")).to_contain_text("No messages yet.")
    page.get_by_label("Message Dana…").fill("Are we going 78 or 80 on Saturday?")
    page.get_by_role("button", name="↑").click()
    expect(page.locator("#msgThread .mbubble.me")).to_contain_text("78 or 80")
    expect(page.get_by_label("Message Dana…")).to_have_value("")

    # The coach sees it in the feed, with the sidebar count, and opens it.
    sign_in(page, coach.user)
    page.goto(base + "/coach/")
    feed = page.locator("#attnCard")
    expect(feed).to_contain_text("78 or 80")
    expect(page.locator("a.navitem .n")).to_be_visible()
    feed.locator("a.attn", has_text="78 or 80").click()
    expect(page).to_have_url(base + f"/coach/athletes/{athlete.pk}/messages/#latest")
    expect(page.locator("#msgThread .mbubble.them")).to_contain_text("78 or 80")
    htmx_idle(page)
    page.get_by_label("Message this athlete…").fill("80, if the first one flies.")
    page.get_by_role("button", name="Send").click()
    expect(page.locator("#msgThread .mbubble.me")).to_contain_text("80, if the first one flies.")

    # Reading the thread handled the feed item.
    page.locator("a.navitem", has_text="Dashboard").click()
    expect(page.locator("#attnCard")).not_to_contain_text("78 or 80")

    # Other items can be marked read with ✓ and cleared.
    item = page.locator("#attnCard .attn-row", has_text="No program yet")
    htmx_idle(page)
    item.get_by_role("button", name="Mark as read: No program yet — build one or apply a template").click()
    expect(page.locator("#attnCard .attn-row.is-read")).to_have_count(1)
    page.get_by_role("button", name="Clear read").click()
    expect(page.locator("#attnCard")).not_to_contain_text("No program yet")

    # The athlete sees the reply badge until they open the thread.
    sign_in(page, athlete.user)
    page.goto(base + "/app/")
    expect(page.locator(".app-head .badge")).to_have_text("1")
    page.locator(".app-tabbar a", has_text="Coach").click()
    expect(page.locator("#msgThread")).to_contain_text("80, if the first one flies.")
    page.goto(base + "/app/")
    expect(page.locator(".app-head .badge")).to_have_count(0)


def test_alerts_go_straight_to_the_thing(page: Page, base, coach, athlete, sign_in):
    import datetime

    from apps.dashboard import alerts
    from apps.programs import services as program_services
    from apps.programs.models import WeekType
    from apps.workouts import sessions
    from apps.workouts.models import IssueReport

    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    today = athlete.today()
    program = program_services.start_program(
        athlete, "Block", today - datetime.timedelta(days=21), 4, week_type, by=coach.user
    )
    old_day = program.weeks.first().days.first()
    from apps.exercises.models import Exercise

    program_services.add_prescription(old_day, Exercise.objects.get(gym=coach.gym, key="sn"), athlete)
    for week in program.weeks.all():
        program_services.set_published(week, True)
    log = sessions.start(athlete, old_day.sessions.get())
    sessions.finish(log, 8, "")
    issue = IssueReport.objects.create(athlete=athlete, session_log=log, kind="pain", text="Left wrist")
    alerts.issue_reported(issue)

    sign_in(page, coach.user)
    page.goto(base + "/coach/")
    # The issue icon in the athletes table goes to the session with the issue, opened.
    page.locator("#rosterBody a.adot--issue").click()
    expect(page).to_have_url(base + f"/coach/athletes/{athlete.pk}/sessions/#issue-{issue.pk}")
    target = page.locator(f"#issue-{issue.pk}")
    expect(target).to_be_visible()
    expect(target).to_be_in_viewport()
    expect(target).to_have_class(re.compile("is-target"))
    page.wait_for_timeout(200)  # let the scroll finish
    header_bottom = page.locator(".coach-topbar").bounding_box()
    box = target.bounding_box()
    assert box["y"] >= header_bottom["y"] + header_bottom["height"]  # not hidden under the sticky header

    # The feed's "no metrics" item lands on the metrics cards.
    page.locator("a.navitem", has_text="Dashboard").click()
    page.locator("#attnCard a.attn", has_text="Missing:").click()
    expect(page).to_have_url(base + f"/coach/athletes/{athlete.pk}/metrics/#metricsPanel")
    expect(page.locator("#metricsPanel")).to_have_class(re.compile("is-target"))
