"""Phase 4: the athlete's session flow, what it records, and what's derived from it."""

import datetime
import json
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Athlete, Coach, MaxEntry, MaxUpdates, MeasurementSource
from apps.exercises.deletion import delete_exercise, deletion_impact
from apps.exercises.models import Exercise
from apps.programs import services
from apps.programs.models import LoadBasis, PrescribedSet, ProgramDay, WeekType
from apps.workouts import history, prs, sessions
from apps.workouts.models import CheckinAnswer, IssueReport, SessionExercise, SessionLog, SetLog

pytestmark = pytest.mark.django_db
DAY = datetime.timedelta(days=1)


def ex(gym, key):
    return Exercise.objects.get(gym=gym, key=key)


@pytest.fixture
def today(athlete):
    return athlete.today()


@pytest.fixture
def program(athlete, coach, today):
    """Three published weeks starting the week before this one."""
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    program = services.start_program(athlete, "Comp Prep", today - 7 * DAY, 3, week_type, by=coach.user)
    for week in program.weeks.all():
        services.set_published(week, True)
    return program


def day_on(program, date):
    return ProgramDay.objects.get(week__program=program, date=date)


def plan(program, date, athlete, *items):
    """Add (exercise, sets, reps, basis, value) prescriptions on `date`; returns the session."""
    day = day_on(program, date)
    for exercise, sets, reps, basis, value in items:
        rx = services.add_prescription(day, exercise, athlete)
        rx.sets, rx.rep_scheme, rx.reps, rx.load_basis, rx.load_value = sets, str(reps), reps, basis, value
        rx.save()
    return day.sessions.get()


@pytest.fixture
def snatch_day(program, athlete, gym, today):
    """Today: snatch 3×2 @ 80% and back squat 2×5 @ 100 kg; snatch max 100 kg."""
    MaxEntry.objects.create(
        athlete=athlete, exercise=ex(gym, "sn"), date=today - 30 * DAY, kg=100, source="coach"
    )
    return plan(
        program,
        today,
        athlete,
        (ex(gym, "sn"), 3, 2, LoadBasis.PERCENT, Decimal("80")),
        (ex(gym, "bsq"), 2, 5, LoadBasis.WEIGHT, Decimal("100")),
    )


@pytest.fixture
def questions(athlete):
    """The mockup's two default check-in questions, copied to the athlete as on joining."""
    from apps.workouts.models import copy_defaults_to, install_default_questions

    install_default_questions(athlete.gym)
    copy_defaults_to(athlete)


def log_sets(log, *rows):
    """rows: (exercise order, set number, kg, reps)."""
    exercises = list(log.exercises.all())
    for order, number, kg, reps in rows:
        sessions.save_set(
            exercises[order],
            number,
            load_kg=Decimal(kg),
            reps=reps,
            duration_seconds=None,
            rir=None,
            done=True,
        )


# ---------------------------------------------------------------- derived values


def test_e1rm_and_best_set():
    assert history.e1rm(Decimal("100"), 3) == Decimal("110.00")
    assert history.e1rm(Decimal("100"), None) is None
    entry = history.Entry(datetime.date(2026, 9, 1), 1, 1, 1, "Snatch")
    entry.sets = [SetLog(load_kg=Decimal("80"), reps=3), SetLog(load_kg=Decimal("85"), reps=1)]
    assert entry.top.load_kg == 85  # heaviest
    assert entry.best_e1rm == Decimal("88.00")  # 80 × 3 beats 85 × 1


def test_sets_text_groups_like_a_prescription():
    sets = [SetLog(load_kg=Decimal("64"), reps=2) for _ in range(3)] + [SetLog(load_kg=Decimal("66"), reps=1)]
    assert history.sets_text(sets, "kg") == "3×2 @ 64 kg, 1×1 @ 66 kg"
    assert history.sets_text([SetLog(reps=10), SetLog(reps=10)], "kg") == "2×10"


def test_plate_rounding_is_in_the_athletes_unit():
    assert sessions.plate_round(Decimal("63.96"), "kg") == Decimal("64")
    assert sessions.plate_round(Decimal("63.70"), "kg") == Decimal("63.5")
    assert sessions.plate_round(Decimal("63.96"), "lb") == Decimal("140")  # 141.0 lb → nearest 2.5


# ---------------------------------------------------------------- starting a session


def test_starting_snapshots_the_prescription(athlete, snatch_day):
    rx = snatch_day.prescriptions.first()
    PrescribedSet.objects.create(prescription=rx, set_number=1, load_value=Decimal("75"))
    log = sessions.start(athlete, snatch_day)
    assert sessions.start(athlete, snatch_day) == log  # starting again resumes it
    se = log.exercises.first()
    assert se.prescribed["load_value"] == "80.00" and se.prescribed["max_kg"] == "100.00"
    assert se.prescribed["set_overrides"][0]["load_value"] == "75.00"
    # The coach edits the day afterwards: "asked for" doesn't change.
    rx.load_value = Decimal("90")
    rx.save()
    se.refresh_from_db()
    assert sessions.prescribed(se).load_value == Decimal("80.00")
    assert log.name == "Snatch + Back Squat" and log.week_type.name == "Accumulation"
    assert not log.checkin_skipped


def test_start_view_rules(athlete_client, athlete, program, gym, today, snatch_day, questions):
    tomorrow = plan(program, today + DAY, athlete, (ex(gym, "cj"), 3, 1, LoadBasis.NONE, None))
    response = athlete_client.post(f"/app/sessions/{tomorrow.pk}/start/")
    assert "unlocks on" in athlete_client.get(response["Location"]).content.decode()
    assert not SessionLog.objects.exists()

    yesterday = plan(program, today - DAY, athlete, (ex(gym, "cj"), 3, 1, LoadBasis.NONE, None))
    response = athlete_client.post(f"/app/sessions/{yesterday.pk}/start/")
    log = SessionLog.objects.get(program_session=yesterday)
    assert log.date == today - DAY and log.checkin_skipped  # filled in afterwards: no check-in
    assert response["Location"] == f"/app/log/{log.pk}/exercise/1/"

    response = athlete_client.post(f"/app/sessions/{snatch_day.pk}/start/")
    log = SessionLog.objects.get(program_session=snatch_day)
    assert response["Location"] == f"/app/log/{log.pk}/checkin/1/"  # today's starts with the check-in


def test_athletes_only_reach_their_own_sessions(client, make_user, coach, athlete, snatch_day):
    other = Athlete.objects.create(user=make_user("jonas@example.com", "Jonas"), coach=coach, gym=coach.gym)
    client.force_login(other.user)
    assert client.post(f"/app/sessions/{snatch_day.pk}/start/").status_code == 404
    log = sessions.start(athlete, snatch_day)
    assert client.get(f"/app/log/{log.pk}/exercise/1/").status_code == 404
    se = log.exercises.first()
    assert client.post(f"/app/log/{log.pk}/sets/{se.pk}/1/", {"load": "50"}).status_code == 404


def test_unpublished_weeks_are_hidden(athlete_client, athlete, program, snatch_day):
    html = athlete_client.get("/app/").content.decode()
    assert "Start session" in html and "Snatch" in html
    ProgramDay.objects.get(sessions=snatch_day).week.__class__.objects.update(published=False)
    html = athlete_client.get("/app/").content.decode()
    assert "hasn't published a week" in html and "Start session" not in html


def test_home_week_strip_statuses(athlete_client, athlete, program, gym, today, snatch_day):
    assert "ws-day today" in athlete_client.get("/app/").content.decode()
    yesterday = today - DAY
    past = plan(program, yesterday, athlete, (ex(gym, "cj"), 3, 1, LoadBasis.NONE, None))
    url = f"/app/?week={yesterday.isoformat()}&day={yesterday.isoformat()}"
    html = athlete_client.get(url).content.decode()
    assert "ws-day missed" in html and "Log this session" in html
    sessions.finish(sessions.start(athlete, past), 7, "")
    html = athlete_client.get(url).content.decode()
    assert "ws-day done" in html and "ws-day missed" not in html
    assert "Review or edit what you logged" in html


# ---------------------------------------------------------------- check-in


def test_checkin_flow(athlete_client, athlete, snatch_day, questions):
    log = sessions.start(athlete, snatch_day)
    html = athlete_client.get(f"/app/log/{log.pk}/checkin/1/").content.decode()
    assert "How recovered do you feel today?" in html and "1 of 3" in html
    assert athlete_client.post(f"/app/log/{log.pk}/checkin/1/", {"value": "11"}).status_code == 200  # invalid
    response = athlete_client.post(f"/app/log/{log.pk}/checkin/1/", {"value": "7"})
    assert response["Location"] == f"/app/log/{log.pk}/checkin/2/"
    response = athlete_client.post(
        f"/app/log/{log.pk}/checkin/2/", {"value": "Other", "other_text": "Tight hamstring"}
    )
    assert response["Location"] == f"/app/log/{log.pk}/checkin/done/"
    answers = list(log.answers.all())
    assert [(a.value, a.other_text) for a in answers] == [("7", ""), ("Other", "Tight hamstring")]
    assert answers[0].question_text == "How recovered do you feel today?"
    html = athlete_client.get(f"/app/log/{log.pk}/checkin/done/").content.decode()
    assert "7 / 10" in html and "Tight hamstring" in html
    response = athlete_client.post(f"/app/log/{log.pk}/checkin/done/", {"action": "start"})
    assert response["Location"] == f"/app/log/{log.pk}/exercise/1/"
    # Rewording the question later keeps the answer's text and its link.
    q = answers[0].question
    q.text = "Recovered?"
    q.save()
    assert CheckinAnswer.objects.get(pk=answers[0].pk).question_text == "How recovered do you feel today?"


def test_skipping_the_checkin(athlete_client, athlete, snatch_day, questions):
    log = sessions.start(athlete, snatch_day)
    athlete_client.post(f"/app/log/{log.pk}/checkin/1/", {"value": "7"})
    athlete_client.post(f"/app/log/{log.pk}/checkin/done/", {"action": "skip"})
    log.refresh_from_db()
    assert log.checkin_skipped and not log.answers.exists()


# ---------------------------------------------------------------- the player


def test_player_suggests_loads_and_last_time(athlete_client, athlete, gym, snatch_day, program, today):
    earlier = plan(program, today - 7 * DAY, athlete, (ex(gym, "sn"), 1, 1, LoadBasis.NONE, None))
    old = sessions.start(athlete, earlier)
    log_sets(old, (0, 1, "78", 1))
    sessions.finish(old, 8, "")

    log = sessions.start(athlete, snatch_day)
    html = athlete_client.get(f"/app/log/{log.pk}/exercise/1/").content.decode()
    assert "≈ 80 kg from your Snatch max" in html
    assert 'data-load="80"' in html and 'data-reps="2"' in html
    assert "last: 78 kg ×1 · 7 days ago" in html
    html = athlete_client.get(f"/app/log/{log.pk}/exercise/2/").content.decode()
    assert 'data-load="100"' in html and "first time" in html and "Finish session" in html


def test_player_uses_the_athletes_unit(athlete_client, athlete, snatch_day):
    athlete.units = "lb"
    athlete.save()
    log = sessions.start(athlete, snatch_day)
    html = athlete_client.get(f"/app/log/{log.pk}/exercise/1/").content.decode()
    assert 'data-load="177.5"' in html  # 80 kg = 176.4 lb → nearest 2.5 lb
    se = log.exercises.first()
    athlete_client.post(f"/app/log/{log.pk}/sets/{se.pk}/1/", {"load": "176.4", "reps": "2", "done": "on"})
    assert SetLog.objects.get().load_kg == Decimal("80.01")  # stored exactly in kg


def test_saving_sets(athlete_client, athlete, snatch_day):
    log = sessions.start(athlete, snatch_day)
    se = log.exercises.first()
    url = f"/app/log/{log.pk}/sets/{se.pk}/2/"
    assert athlete_client.post(url, {"load": "80", "reps": "2", "rir": "5", "done": "on"}).json() == {
        "saved": True
    }
    athlete_client.post(url, {"load": "82.5", "reps": "2", "rir": "", "done": ""})  # changed and unticked
    s = SetLog.objects.get()
    assert (s.set_number, s.load_kg, s.reps, s.rir, s.done) == (2, Decimal("82.5"), 2, None, False)
    assert athlete_client.post(url, {"load": "lots"}).status_code == 400
    html = athlete_client.get(f"/app/log/{log.pk}/exercise/1/").content.decode()
    assert 'data-load="82.5"' in html


def test_timed_work_is_logged_in_seconds(athlete_client, athlete, gym, program, today):
    session = plan(program, today, athlete, (ex(gym, "mob"), 1, 10, LoadBasis.NONE, None))
    rx = session.prescriptions.get()
    rx.rep_scheme, rx.reps, rx.duration_seconds = "10 min", None, 600
    rx.save()
    log = sessions.start(athlete, session)
    html = athlete_client.get(f"/app/log/{log.pk}/exercise/1/").content.decode()
    assert 'data-time="10"' in html and 'data-time-unit="min"' in html
    se = log.exercises.get()
    athlete_client.post(
        f"/app/log/{log.pk}/sets/{se.pk}/1/", {"time": "12", "time_unit": "min", "done": "on"}
    )
    assert SetLog.objects.get().duration_seconds == 720


# ---------------------------------------------------------------- finishing and editing


def test_finish_done_and_the_24_hour_edit_window(athlete_client, athlete, snatch_day):
    log = sessions.start(athlete, snatch_day)
    log_sets(log, (0, 1, "80", 2), (0, 2, "80", 2))
    assert (
        athlete_client.post(f"/app/log/{log.pk}/finish/", {"comment": "ok"}).status_code == 200
    )  # RPE needed
    response = athlete_client.post(f"/app/log/{log.pk}/finish/", {"rpe": "8", "comment": "Felt quick"})
    assert response["Location"] == f"/app/log/{log.pk}/done/"
    log.refresh_from_db()
    assert log.finished and log.session_rpe == 8 and log.comment == "Felt quick"
    html = athlete_client.get(response["Location"]).content.decode()
    assert "2/5" in html and "session RPE" in html

    # Editing within 24 hours works and returns to Progress.
    response = athlete_client.post(f"/app/log/{log.pk}/finish/", {"rpe": "9", "comment": "Felt quick"})
    assert response["Location"] == "/app/progress/"
    se = log.exercises.first()
    assert (
        athlete_client.post(f"/app/log/{log.pk}/sets/{se.pk}/3/", {"load": "80", "done": "on"}).status_code
        == 200
    )

    SessionLog.objects.filter(pk=log.pk).update(finished_at=timezone.now() - datetime.timedelta(hours=25))
    assert athlete_client.post(f"/app/log/{log.pk}/sets/{se.pk}/3/", {"load": "90"}).status_code == 409
    assert athlete_client.get(f"/app/log/{log.pk}/finish/")["Location"] == f"/app/log/{log.pk}/exercise/1/"
    assert "read only now" in athlete_client.get(f"/app/log/{log.pk}/exercise/1/").content.decode()


def test_paused_sessions_resume_where_they_left_off(athlete_client, athlete, snatch_day):
    log = sessions.start(athlete, snatch_day)
    log.checkin_skipped = True
    log.save()
    log_sets(log, (0, 1, "80", 2), (0, 2, "80", 2), (0, 3, "80", 2))
    response = athlete_client.get(f"/app/log/{log.pk}/pause/")
    assert "Session paused" in athlete_client.get(response["Location"]).content.decode()
    assert athlete_client.get(f"/app/log/{log.pk}/")["Location"] == f"/app/log/{log.pk}/exercise/2/"
    assert "Resume session" in athlete_client.get("/app/").content.decode()


def test_reporting_an_issue(athlete_client, athlete, snatch_day):
    log = sessions.start(athlete, snatch_day)
    response = athlete_client.post(f"/app/log/{log.pk}/issue/", {"kind": "pain", "text": "Left wrist"})
    assert "Left wrist" in response.content.decode()
    assert json.loads(response["HX-Trigger-After-Swap"]) == {"closeModal": True}
    issue = IssueReport.objects.get()
    assert (issue.athlete, issue.session_log, issue.kind) == (athlete, log, "pain")


# ---------------------------------------------------------------- PRs and maxes


def _finish_heavy(athlete, snatch_day, kg="105"):
    log = sessions.start(athlete, snatch_day)
    log_sets(log, (0, 1, "80", 2), (0, 2, kg, 1), (1, 1, "140", 5))
    sessions.finish(log, 9, "")
    return log


def test_prs_wait_for_the_coach_by_default(coach_client, athlete, gym, snatch_day):
    _finish_heavy(athlete, snatch_day)
    assert athlete.max_updates == MaxUpdates.APPROVE
    assert athlete.current_max(ex(gym, "sn")).kg == 100  # unchanged
    pending = prs.pending(athlete)
    assert [(c.exercise.name, c.set_log.load_kg) for c in pending] == [("Snatch", Decimal("105.00"))]
    # Back squat has no max on file, so a heavy squat doesn't create one.
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/metrics/").content.decode()
    assert "Use as working max" in html and "105 kg × 1" in html

    response = coach_client.post(
        f"/coach/athletes/{athlete.pk}/prs/{pending[0].set_log.pk}/",
        {"decision": "use"},
        HTTP_HX_REQUEST="true",
    )
    assert "Snatch max is now 105 kg" in response["HX-Trigger"]
    entry = athlete.current_max(ex(gym, "sn"))
    assert (entry.kg, entry.source) == (Decimal("105.00"), MeasurementSource.COACH)
    assert prs.pending(athlete) == []


def test_keeping_the_current_max(coach_client, make_user, athlete, gym, snatch_day):
    _finish_heavy(athlete, snatch_day)
    set_id = prs.pending(athlete)[0].set_log.pk
    other = Coach.objects.create(user=make_user("sam@example.com", "Sam"), gym=gym)
    sam = Client()
    sam.force_login(other.user)  # another coach can't decide for this athlete
    assert sam.post(f"/coach/athletes/{athlete.pk}/prs/{set_id}/", {"decision": "use"}).status_code == 404
    coach_client.post(
        f"/coach/athletes/{athlete.pk}/prs/{set_id}/", {"decision": "keep"}, HTTP_HX_REQUEST="true"
    )
    assert prs.pending(athlete) == [] and athlete.current_max(ex(gym, "sn")).kg == 100
    # A later, lighter best above the max still comes up for review.
    log = SessionLog.objects.get()
    sessions.save_set(
        log.exercises.first(), 3, load_kg=Decimal("102"), reps=1, duration_seconds=None, rir=None, done=True
    )
    assert [c.set_log.load_kg for c in prs.pending(athlete)] == [Decimal("102.00")]


def test_automatic_prs_follow_session_edits(coach_client, athlete, gym, snatch_day):
    coach_client.post(
        f"/coach/athletes/{athlete.pk}/max-updates/", {"max_updates": "auto"}, HTTP_HX_REQUEST="true"
    )
    athlete.refresh_from_db()
    log = _finish_heavy(athlete, snatch_day)
    entry = athlete.current_max(ex(gym, "sn"))
    assert (entry.kg, entry.source, entry.date) == (Decimal("105.00"), MeasurementSource.SESSION, log.date)
    # A typo fixed within the 24 hours takes the automatic max back out.
    se = log.exercises.first()
    sessions.save_set(se, 2, load_kg=Decimal("95"), reps=1, duration_seconds=None, rir=None, done=True)
    assert athlete.current_max(ex(gym, "sn")).kg == 100
    assert not MaxEntry.objects.filter(source=MeasurementSource.SESSION).exists()


def test_progress_lists_prs_and_recent_sessions(athlete_client, athlete, snatch_day):
    _finish_heavy(athlete, snatch_day)
    html = athlete_client.get("/app/progress/").content.decode()
    assert "Snatch" in html and "105 kg ×1" in html and "best e1RM 109 kg" in html
    assert "Back Squat" in html and "140 kg ×5" in html and "RPE 9" in html and ">edit<" in html


def test_streak_counts_back_from_today(athlete, gym, program, today):
    s1 = plan(program, today - 2 * DAY, athlete, (ex(gym, "cj"), 1, 1, LoadBasis.NONE, None))
    s2 = plan(program, today - DAY, athlete, (ex(gym, "cj"), 1, 1, LoadBasis.NONE, None))
    plan(program, today, athlete, (ex(gym, "cj"), 1, 1, LoadBasis.NONE, None))
    sessions.finish(sessions.start(athlete, s2), 7, "")
    assert history.streak(athlete, today) == 1  # today isn't missed yet; the day before yesterday was
    sessions.finish(sessions.start(athlete, s1), 7, "")
    assert history.streak(athlete, today) == 2


# ---------------------------------------------------------------- the coach's side


def test_sessions_tab_shows_asked_beside_did(coach_client, athlete, snatch_day):
    log = _finish_heavy(athlete, snatch_day)
    CheckinAnswer.objects.create(session_log=log, question_text="Recovered?", type="scale", value="6")
    url = f"/coach/athletes/{athlete.pk}/sessions/"
    html = coach_client.get(url).content.decode()
    assert "asked 3×2 @ 80% (≈ 80 kg)" in html
    assert "did 1×2 @ 80 kg, 1×1 @ 105 kg · e1RM 109 kg" in html and "2/3 sets" in html
    assert "asked 2×5 @ 100 kg" in html and "did 1×5 @ 140 kg" in html
    assert "readiness 6/10" in html and "RPE 9" in html and "PR day" in html
    results = coach_client.get(url, {"q": "clean"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="sessLog")
    assert 'id="sessLog"' in results.content.decode() and "No sessions" in results.content.decode()


def test_logged_days_are_protected_on_the_board(coach_client, athlete, program, gym, today, snatch_day):
    log = sessions.start(athlete, snatch_day)
    week = snatch_day.day.week
    assert services.locked_day_ids(week) == set()  # paused sessions don't lock the day
    sessions.finish(log, 7, "")
    assert services.locked_day_ids(week) == {snatch_day.day_id}
    services.clear_week(week)
    assert snatch_day.prescriptions.count() == 2
    first = program.weeks.get(order=0)
    with pytest.raises(services.HasLoggedSessions):
        services.duplicate_week(first)
    with pytest.raises(services.HasLoggedSessions):
        services.delete_week(first)
    response = coach_client.post(
        f"/coach/athletes/{athlete.pk}/program/sessions/{snatch_day.pk}/delete/", HTTP_HX_REQUEST="true"
    )
    assert "has logged this session" in response["HX-Trigger"]
    # Removing every exercise keeps the (logged) session, so the day stays done.
    for rx in list(snatch_day.prescriptions.all()):
        services.remove_prescription(rx)
    assert SessionLog.objects.get().program_session_id == snatch_day.pk
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/program/").content.decode()
    assert "✓ done" in html


def test_deleting_a_logged_exercise_keeps_the_history_by_name(athlete, gym, snatch_day):
    log = _finish_heavy(athlete, snatch_day)
    squat = ex(gym, "bsq")
    squat.archived = True
    squat.save()
    impact = deletion_impact(squat)
    assert impact["logged"] == 1 and impact["logged_by"] == ["Maya Torres"]
    delete_exercise(squat)
    se = SessionExercise.objects.get(session_log=log, exercise_name="Back Squat")
    assert se.exercise is None and se.sets.count() == 1


def test_rail_shows_history_and_sorts_by_last_done(coach_client, athlete, gym, snatch_day):
    _finish_heavy(athlete, snatch_day)
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/program/library/").content.decode()
    assert "105 kg ×1 · today" in html and "Not logged by Maya yet" in html
    first_two = [html.index("Back Squat"), html.index("Snatch")]
    assert max(first_two) < html.index("Clean &amp; Jerk")  # done ones first
    az = coach_client.get(f"/coach/athletes/{athlete.pk}/program/library/", {"sort": "az"}).content.decode()
    assert az.index("Back Squat") < az.index("Clean &amp; Jerk") < az.index("Snatch")


def test_profile_lists_metrics_in_the_athletes_unit(athlete_client, athlete, gym):
    athlete.height_cm, athlete.units = Decimal("180.0"), "lb"
    athlete.save()
    MaxEntry.objects.create(
        athlete=athlete, exercise=ex(gym, "sn"), date=athlete.today(), kg=100, source="coach"
    )
    html = athlete_client.get("/app/profile/").content.decode()
    assert "180 cm" in html and "220.5 lb" in html and "missing — tap to add" in html
