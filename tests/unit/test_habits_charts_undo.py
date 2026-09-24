"""Phase 7: habits, charts and undo on the program board."""

import datetime
import json
from decimal import Decimal

import pytest

from apps.accounts.models import BodyweightEntry
from apps.exercises.models import Exercise
from apps.library import apply
from apps.library import services as library_services
from apps.library.models import TemplateHabit, TemplateKind
from apps.programs import habits, undo
from apps.programs import services as program_services
from apps.programs.models import EditHistory, Habit, HabitLog, LoadBasis, Prescription, WeekType
from apps.workouts import charts, sessions

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}
DAY = datetime.timedelta(days=1)


def ex(gym, key):
    return Exercise.objects.get(gym=gym, key=key)


def toast(response):
    return json.loads(response["HX-Trigger"])["toast"]["message"]


@pytest.fixture
def program(athlete, coach):
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    program = program_services.start_program(
        athlete, "Block", athlete.today() - 14 * DAY, 3, week_type, by=coach.user
    )
    for week in program.weeks.all():
        program_services.set_published(week, True)
    return program


def habit(athlete, cadence="daily", name="Fruit"):
    h = habits.prescribe(athlete, name, "🍎", cadence, "")
    Habit.objects.filter(pk=h.pk).update(created_at=h.created_at - datetime.timedelta(days=30))
    h.refresh_from_db()
    return h


def tick(h, *days_ago):
    today = h.athlete.today()
    for d in days_ago:
        HabitLog.objects.create(habit=h, date=today - d * DAY)


# ---------------------------------------------------------------- habits


def test_daily_streak_ignores_today_until_it_is_over(athlete):
    h = habit(athlete)
    tick(h, 1, 2, 3, 5)
    assert habits.streak(h, athlete.today()) == 3
    tick(h, 0)
    assert habits.streak(h, athlete.today()) == 4


def test_training_day_habits_only_show_on_session_days(athlete, program, gym):
    h = habit(athlete, "training", "Mobility")
    today = athlete.today()
    assert habits.for_day(athlete, today) == []
    day = program.weeks.get(days__date=today).days.get(date=today)
    program_services.add_prescription(day, ex(gym, "sn"), athlete)
    assert [i["habit"] for i in habits.for_day(athlete, today)] == [h]


def test_weekly_targets(athlete):
    h = habit(athlete, "3x", "Walk")
    today = athlete.today()
    week_start = athlete.gym.week_start_for(today)
    last_week = week_start - 7 * DAY
    for i in range(3):
        HabitLog.objects.create(habit=h, date=last_week + i * DAY)
    assert habits.streak(h, today) == 1  # last week met; this week not over yet
    for i in range(3):
        HabitLog.objects.get_or_create(habit=h, date=week_start + i * DAY)
    item = next(i for i in habits.for_day(athlete, week_start + 3 * DAY) if i["habit"] == h)
    if week_start + 3 * DAY <= today:
        assert item["met_for_week"] and item["week_count"] == 3
    assert habits.streak(h, today) == 2


def test_athlete_ticks_today_and_yesterday_only(athlete_client, athlete):
    h = habit(athlete)
    response = athlete_client.post(f"/app/habits/{h.pk}/tick/", {"day": "today"}, **HX)
    assert "habit-row done" in response.content.decode()
    athlete_client.post(f"/app/habits/{h.pk}/tick/", {"day": "yesterday"}, **HX)
    assert set(h.logs.values_list("date", flat=True)) == {athlete.today(), athlete.today() - DAY}
    athlete_client.post(f"/app/habits/{h.pk}/tick/", {"day": "today"}, **HX)  # untick
    assert not h.logs.filter(date=athlete.today()).exists()
    with pytest.raises(habits.CannotTick):
        habits.toggle(h, athlete.today() - 2 * DAY)
    assert "Today's habits" in athlete_client.get("/app/").content.decode()


def test_coach_prescribes_and_stops_habits(coach_client, athlete, program):
    base = f"/coach/athletes/{athlete.pk}/"
    response = coach_client.post(
        base + "habits/add/", {"name": "Sleep 8 hours", "emoji": "😴", "cadence": "daily", "note": ""}, **HX
    )
    assert "Sleep 8 hours" in response.content.decode()
    again = coach_client.post(
        base + "habits/add/", {"name": "sleep 8 HOURS", "emoji": "😴", "cadence": "daily", "note": ""}, **HX
    )
    assert "already has" in toast(again)
    h = Habit.objects.get()
    tick(h, 1)
    assert "Sleep 8 hours" in coach_client.get(base + "program/").content.decode()
    coach_client.post(base + f"habits/{h.pk}/remove/", **HX)
    h.refresh_from_db()
    assert h.archived_at and h.logs.count() == 1  # archived, history kept


def test_applying_a_template_prescribes_its_habits(athlete, coach, gym):
    template = library_services.new_template(gym, TemplateKind.PROGRAM, coach.user)
    library_services.add_slot(template.weeks.get().sessions.first(), ex(gym, "sn"))
    TemplateHabit.objects.create(template=template, name="Sleep 8 hours", emoji="😴", cadence="daily")
    TemplateHabit.objects.create(template=template, name="Fruit", emoji="🍎", cadence="daily")
    habit(athlete, name="Fruit")  # already has it
    _program, _first, added = apply.confirm(
        athlete, template, [0, 2, 4], apply.DEFAULTS, "new:next", False, coach.user
    )
    assert added == 1
    assert Habit.objects.get(name="Sleep 8 hours").source_template == template


# ---------------------------------------------------------------- undo


def test_undo_restores_edits_within_a_week(coach_client, athlete, program, gym):
    week = program.weeks.last()
    base = f"/coach/athletes/{athlete.pk}/program/"
    days = list(week.days.all())
    coach_client.post(base + "add/", {"day": days[0].pk, "exercise": ex(gym, "sn").pk}, **HX)
    rx = Prescription.objects.get()
    coach_client.post(
        base + f"rx/{rx.pk}/",
        {"sets": "5", "rep_scheme": "2", "load_basis": "percent", "load_value": "80"},
        **HX,
    )
    coach_client.post(base + f"rx/{rx.pk}/move/", {"day": days[3].pk, "index": "0"}, **HX)
    html = coach_client.get(base + f"?week={week.pk}").content.decode()
    assert "Undo: Move Snatch" in html

    assert "Undone: Move Snatch" in toast(coach_client.post(base + f"weeks/{week.pk}/undo/", **HX))
    rx.refresh_from_db()
    assert rx.session.day == days[0] and rx.load_value == Decimal("80")
    coach_client.post(base + f"weeks/{week.pk}/undo/", **HX)  # the edit
    rx.refresh_from_db()
    assert rx.load_value != Decimal("80")
    coach_client.post(base + f"weeks/{week.pk}/undo/", **HX)  # the add
    assert not Prescription.objects.exists()
    assert "Nothing to undo" in toast(coach_client.post(base + f"weeks/{week.pk}/undo/", **HX))


def test_undo_never_removes_a_logged_session(athlete, program, gym, coach):
    week = program.weeks.get(days__date=athlete.today())
    day = week.days.get(date=athlete.today())
    undo.record(week, coach.user, "Add Snatch")  # the empty week
    program_services.add_prescription(day, ex(gym, "sn"), athlete)
    log = sessions.start(athlete, day.sessions.get())
    sessions.finish(log, 7, "")
    assert undo.undo(week) == "Add Snatch"
    assert day.sessions.get().prescriptions.count() == 1  # kept: it was logged


def test_undo_history_is_capped(athlete, program, coach):
    week = program.weeks.first()
    for i in range(undo.UNDO_DEPTH + 5):
        undo.record(week, coach.user, f"Edit {i}")
    assert EditHistory.objects.filter(program_week=week).count() == undo.UNDO_DEPTH
    assert undo.latest(week).label == f"Edit {undo.UNDO_DEPTH + 4}"


# ---------------------------------------------------------------- charts


def _log(athlete, program, gym, days_ago, kg, reps=1):
    date = athlete.today() - days_ago * DAY
    day = program.weeks.get(days__date=date).days.get(date=date)
    rx = program_services.add_prescription(day, ex(gym, "sn"), athlete)
    rx.load_basis = LoadBasis.NONE
    rx.save()
    log = sessions.start(athlete, day.sessions.get())
    sessions.save_set(
        log.exercises.get(), 1, load_kg=Decimal(kg), reps=reps, duration_seconds=None, rir=None, done=True
    )
    sessions.finish(log, 7, "")


def test_e1rm_chart_has_phase_bands_and_bodyweight(athlete, program, gym):
    BodyweightEntry.objects.create(athlete=athlete, date=athlete.today() - 20 * DAY, kg=65, source="athlete")
    BodyweightEntry.objects.create(athlete=athlete, date=athlete.today() - 5 * DAY, kg=64, source="athlete")
    for days_ago, kg in [(12, 70), (8, 72), (3, 75)]:
        _log(athlete, program, gym, days_ago, kg)
    points = charts.e1rm_points(athlete, ex(gym, "sn"))
    assert [p[1] for p in points] == [Decimal("72.33"), Decimal("74.40"), Decimal("77.50")]
    svg = charts.e1rm_chart(athlete, ex(gym, "sn"), "kg")
    assert "ACCUMULATION" in svg and "stroke-dasharray" in svg and "bw 64 kg" in svg
    assert "Not enough" in charts.e1rm_chart(athlete, ex(gym, "cj"), "kg")


def test_weekly_volume(athlete, program, gym):
    _log(athlete, program, gym, 1, 100, reps=3)
    rows = charts.weekly(athlete)
    assert len(rows) == 8 and sum(v for _s, v, _c in rows) == Decimal("300")


def test_overview_and_progress_pages(coach_client, athlete, program, gym, client):
    for days_ago, kg in [(8, 72), (3, 75)]:
        _log(athlete, program, gym, days_ago, kg)
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/overview/").content.decode()
    assert (
        "Estimated 1RM trend" in html and "<circle" in html and "Lifetime PRs" in html and "75 kg ×1" in html
    )
    chart = coach_client.get(
        f"/coach/athletes/{athlete.pk}/overview/",
        {"lift": ex(gym, "cj").pk},
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="e1rmChart",
    ).content.decode()
    assert chart.startswith('<svg class="spark" id="e1rmChart"') and "Not enough" in chart
    client.force_login(athlete.user)
    progress = client.get("/app/progress/").content.decode()
    assert "Snatch e1RM" in progress and "▲ +3 kg" in progress


def test_rail_shows_sparklines(coach_client, athlete, program, gym):
    for days_ago, kg in [(8, 72), (3, 75)]:
        _log(athlete, program, gym, days_ago, kg)
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/program/library/").content.decode()
    assert '<svg width="52" height="18"' in html


def test_a_new_habit_counts_yesterday_ticked_late(athlete):
    h = habits.prescribe(athlete, "Walk", "🚶", "daily", "")  # created just now
    tick(h, 0, 1)
    assert habits.streak(h, athlete.today()) == 2
