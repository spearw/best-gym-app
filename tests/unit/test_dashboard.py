"""Phase 6: the attention feed, the dashboard, and coach–athlete messages."""

import datetime
import json
from decimal import Decimal

import pytest

from apps.accounts.models import Athlete, BodyweightEntry, Coach, MaxEntry, MaxUpdates
from apps.dashboard import alerts
from apps.dashboard.models import Notification, NotificationKind
from apps.exercises.models import Exercise
from apps.messaging.models import Message, Thread
from apps.programs import services as program_services
from apps.programs.models import WeekType
from apps.workouts import sessions
from apps.workouts.models import IssueReport

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}
DAY = datetime.timedelta(days=1)


def ex(gym, key):
    return Exercise.objects.get(gym=gym, key=key)


def kinds(coach):
    return sorted(n.kind for n in alerts.feed(coach))


@pytest.fixture
def program(athlete, coach):
    """Three published weeks from last week, so "3 days from today" is inside it whatever
    the weekday (with two weeks it ran out on Fridays to Sundays)."""
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    program = program_services.start_program(
        athlete, "Block", athlete.today() - 7 * DAY, 3, week_type, by=coach.user
    )
    for week in program.weeks.all():
        program_services.set_published(week, True)
    return program


def plan(program, date, athlete, gym, key="sn"):
    day = program.weeks.get(days__date=date).days.get(date=date)
    rx = program_services.add_prescription(day, ex(gym, key), athlete)
    return rx.session


# ---------------------------------------------------------------- conditions


def test_no_program_and_missing_metrics(coach, athlete):
    alerts.sync_athlete(athlete)
    assert kinds(coach) == [NotificationKind.METRICS_MISSING, NotificationKind.PROGRAM_ENDING]
    assert "No program yet" in alerts.feed(coach).get(kind="program_ending").text


def test_program_running_out_clears_when_weeks_are_added(coach, athlete, gym, program):
    last = athlete.today() + 3 * DAY
    plan(program, last, athlete, gym)
    alerts.sync_athlete(athlete)
    row = alerts.feed(coach).get(kind="program_ending")
    assert "runs out" in row.text and "(3 days)" in row.text
    week_type = WeekType.objects.get(gym=gym, name="Accumulation")
    week = program_services.add_week(program, week_type)
    program_services.add_prescription(week.days.last(), ex(gym, "cj"), athlete)
    alerts.sync_athlete(athlete)
    assert not alerts.feed(coach).filter(kind="program_ending").exists()


def test_missed_sessions_leave_once_logged(coach, athlete, gym, program):
    session = plan(program, athlete.today() - DAY, athlete, gym)
    alerts.sync_athlete(athlete)
    assert "Missed" in alerts.feed(coach).get(kind="missed").text
    sessions.finish(sessions.start(athlete, session), 7, "")
    alerts.sync_athlete(athlete)
    assert not alerts.feed(coach).filter(kind="missed").exists()


def test_dismissed_conditions_stay_dismissed_until_they_change(coach, coach_client, athlete):
    alerts.sync_athlete(athlete)
    row = alerts.feed(coach).get(kind="metrics_missing")
    coach_client.post(f"/coach/feed/{row.pk}/read/", **HX)
    alerts.sync_athlete(athlete)
    row.refresh_from_db()
    assert row.read_at is not None  # not reopened by the next check
    coach_client.post("/coach/feed/clear/", **HX)
    assert not alerts.feed(coach).filter(kind="metrics_missing").exists()


# ---------------------------------------------------------------- events


def test_messages_notify_the_coach_and_clear_when_read(coach, athlete_client, athlete, client):
    athlete_client.post("/app/coach/send/", {"body": "Are we going 78 or 80?"}, **HX)
    row = alerts.feed(coach).get(kind="message")
    assert "78 or 80" in row.text and row.read_at is None
    client.force_login(coach.user)
    html = client.get(f"/coach/athletes/{athlete.pk}/messages/").content.decode()
    assert "Are we going 78 or 80?" in html
    row.refresh_from_db()
    assert row.cleared_at is not None  # opening the thread handled it
    assert Message.objects.get().read_at is not None


def test_coach_reply_reaches_the_athlete_with_a_badge(coach_client, athlete, client):
    coach_client.post(
        f"/coach/athletes/{athlete.pk}/messages/send/", {"body": "80, if the first one flies."}, **HX
    )
    client.force_login(athlete.user)
    home = client.get("/app/").content.decode()
    assert 'class="badge"' in home and "1 unread" in home
    thread = client.get("/app/coach/").content.decode()
    assert "80, if the first one flies." in thread and "mob-msgs" in thread
    assert 'class="badge"' not in client.get("/app/").content.decode()  # read now


def test_blank_messages_are_ignored(athlete_client):
    athlete_client.post("/app/coach/send/", {"body": "   "}, **HX)
    assert not Message.objects.exists()


def test_threads_are_per_coach(coach, athlete, make_user):
    old = Thread.for_athlete(athlete)
    Message.objects.create(thread=old, sender=coach.user, body="Old coach's note")
    other = Coach.objects.create(user=make_user("sam@example.com", "Sam"), gym=coach.gym)
    athlete.coach = other
    athlete.save()
    assert not Thread.for_athlete(athlete).messages.exists()  # a fresh thread with the new coach


def test_issues_notify_and_resolve(coach, coach_client, athlete, program, gym):
    from django.test import Client

    session = plan(program, athlete.today(), athlete, gym)
    log = sessions.start(athlete, session)
    athlete_client = Client()  # coach_client and athlete_client would share one browser
    athlete_client.force_login(athlete.user)
    athlete_client.post(f"/app/log/{log.pk}/issue/", {"kind": "pain", "text": "Left wrist"}, **HX)
    row = alerts.feed(coach).get(kind="issue")
    assert "Left wrist" in row.text and row.link.endswith("/sessions/")
    issue = IssueReport.objects.get()
    response = coach_client.post(f"/coach/athletes/{athlete.pk}/issues/{issue.pk}/resolve/", **HX)
    assert "resolved" in response.content.decode()
    row.refresh_from_db()
    assert row.cleared_at is not None


def test_waiting_prs_notify_and_clear_when_decided(coach, coach_client, athlete, program, gym):
    MaxEntry.objects.create(
        athlete=athlete, exercise=ex(gym, "sn"), date=athlete.today() - 30 * DAY, kg=100, source="coach"
    )
    session = plan(program, athlete.today(), athlete, gym)
    log = sessions.start(athlete, session)
    sessions.save_set(
        log.exercises.get(), 1, load_kg=Decimal("105"), reps=1, duration_seconds=None, rir=None, done=True
    )
    sessions.finish(log, 9, "")
    row = alerts.feed(coach).get(kind="pr")
    assert "Snatch 105 kg × 1" in row.text
    set_id = log.exercises.get().sets.get().pk
    coach_client.post(f"/coach/athletes/{athlete.pk}/prs/{set_id}/", {"decision": "use"}, **HX)
    row.refresh_from_db()
    assert row.cleared_at is not None


def test_automatic_max_updates_are_reported(coach, athlete, program, gym):
    athlete.max_updates = MaxUpdates.AUTO
    athlete.save()
    MaxEntry.objects.create(
        athlete=athlete, exercise=ex(gym, "sn"), date=athlete.today() - 30 * DAY, kg=100, source="coach"
    )
    log = sessions.start(athlete, plan(program, athlete.today(), athlete, gym))
    sessions.save_set(
        log.exercises.get(), 1, load_kg=Decimal("104"), reps=1, duration_seconds=None, rir=None, done=True
    )
    sessions.finish(log, 9, "")
    assert "Snatch max updated to 104 kg" in alerts.feed(coach).get(kind="pr").text


# ---------------------------------------------------------------- the dashboard


def test_dashboard(coach_client, coach, athlete, program, gym):
    BodyweightEntry.objects.create(athlete=athlete, date=athlete.today(), kg=64, source="athlete")
    session = plan(program, athlete.today() - DAY, athlete, gym)
    plan(program, athlete.today(), athlete, gym, "cj")
    sessions.finish(sessions.start(athlete, session), 8, "Felt quick")
    html = coach_client.get("/coach/").content.decode()
    assert "Needs your attention" in html and "Maya Torres" in html
    assert "7-day compliance" in html and "100%" in html  # 1 of 1 scheduled days before today done
    assert "Felt quick" in html  # recent sessions
    assert "1 exercise" in html  # today's session
    assert 'class="n"' in html  # the sidebar count
    rows = coach_client.get("/coach/", {"sort": "name"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="rosterBody")
    assert rows.content.decode().startswith('<tbody id="rosterBody">')


def test_feed_polling_updates_the_sidebar_count(coach_client, athlete):
    alerts.sync_athlete(athlete)
    html = coach_client.get(
        "/coach/feed/", HTTP_HX_REQUEST="true", HTTP_HX_TARGET="attnCard"
    ).content.decode()
    assert 'id="attnCard"' in html and 'hx-swap-oob="true"' in html and 'class="n"' in html


def test_other_coaches_see_nothing(client, make_user, coach, athlete):
    alerts.sync_athlete(athlete)
    other = Coach.objects.create(user=make_user("sam@example.com", "Sam"), gym=coach.gym)
    Athlete.objects.create(user=make_user("x@example.com", "X"), coach=other, gym=coach.gym)
    client.force_login(other.user)
    assert "Maya" not in client.get("/coach/").content.decode()
    row = Notification.objects.filter(recipient=coach.user).first()
    assert client.post(f"/coach/feed/{row.pk}/read/", **HX).status_code == 404
    assert client.get(f"/coach/athletes/{athlete.pk}/messages/thread/").status_code == 404


def test_nightly_syncs_every_coach(athlete, coach):
    from django.core.management import call_command

    call_command("nightly")
    assert alerts.feed(coach).filter(kind="program_ending").exists()


def test_toast_on_clear(coach_client):
    response = coach_client.post("/coach/feed/clear/", **HX)
    assert json.loads(response["HX-Trigger"])["toast"]["message"] == "Nothing read to clear"


def test_short_times():
    from django.utils import timezone

    from apps.dashboard.templatetags.ago import ago

    now = timezone.now()
    assert [
        ago(now - datetime.timedelta(**d))
        for d in ({"seconds": 5}, {"minutes": 5}, {"hours": 2}, {"days": 3})
    ] == [
        "just now",
        "5m ago",
        "2h ago",
        "3d ago",
    ]


def test_alert_links_go_to_the_item(coach, athlete, program, gym):
    from apps.workouts.models import SessionLog

    alerts.sync_athlete(athlete)
    links = {n.kind: alerts.link_for(n) for n in alerts.feed(coach)}
    assert links["metrics_missing"].endswith("/metrics/#metricsPanel")
    assert "program/?week=" in links["program_ending"] or links["program_ending"].endswith("/program/")
    old = SessionLog.objects.create(athlete=athlete, date=athlete.today() - 70 * DAY, name="Old")
    issue = IssueReport.objects.create(athlete=athlete, session_log=old, kind="pain")
    alerts.issue_reported(issue)
    row = alerts.feed(coach).get(kind="issue")
    assert alerts.link_for(row).endswith(
        f"/sessions/?range=all#issue-{issue.pk}"
    )  # outside the default 8 weeks
    session = plan(program, athlete.today() - DAY, athlete, gym)
    alerts.sync_athlete(athlete)
    missed = alerts.feed(coach).get(kind="missed")
    assert alerts.link_for(missed).endswith(f"?week={session.day.week_id}#day-{session.day_id}")
