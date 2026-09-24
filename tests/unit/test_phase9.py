"""Phase 9, from the client's spreadsheet: RIR ranges and rep ranges, warm-up drills,
section headings and supersets, short-answer check-in questions, program notes, and the
anonymised demo athlete on "Meso 1"."""

import json
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.exercises.models import Exercise
from apps.library import apply
from apps.library import services as library_services
from apps.library.models import Template, TemplateKind
from apps.programs import services as program_services
from apps.programs import undo
from apps.programs.forms import PrescriptionForm
from apps.programs.models import LoadBasis, WeekType
from apps.programs.prescriptions import layout, parse_rep_scheme, parse_rir, summary
from apps.workouts import sessions
from apps.workouts.models import CheckinAnswer, CheckinQuestion, QuestionType

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def ex(gym, key):
    return Exercise.objects.get(gym=gym, key=key)


@pytest.fixture
def drill(gym):
    e = Exercise.objects.create(
        gym=gym,
        name="Deep Squat Lat Hang",
        category=ex(gym, "mob").category,
        youtube_url="https://www.youtube.com/watch?v=abc",
        warmup=True,
    )
    return e


@pytest.fixture
def day(athlete, coach):
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    program = program_services.start_program(athlete, "Meso", athlete.today(), 1, week_type, by=coach.user)
    week = program.weeks.get()
    program_services.set_published(week, True)
    return week.days.get(date=athlete.today())


def dose(rx, **fields):
    """Change a few fields (only those, so a stale `order` in memory isn't written back)."""
    type(rx).objects.filter(pk=rx.pk).update(**fields)
    rx.refresh_from_db()
    return rx


def post(**data):
    from django.http import QueryDict
    from django.utils.http import urlencode

    return QueryDict(urlencode(data))


# ---------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    "text, expected",
    [
        ("10-12", (10, None)),
        ("15–20 each", (15, None)),
        ("10-12/leg", (10, None)),
        ("20-30 min", (None, 1200)),
        ("5-3-1", (None, None)),  # a wave, not a range
        ("12-10", (None, None)),  # not low-high
        ("x 5 breaths", (None, None)),
    ],
)
def test_rep_ranges_count_the_low_end(text, expected):
    assert parse_rep_scheme(text) == expected


def test_rir_targets_take_a_number_or_a_range():
    assert parse_rir("2") == (2, None)
    assert parse_rir(" 1 - 2 ") == (1, 2)
    assert parse_rir("3-2") == (2, 3)
    assert parse_rir("2-2") == (2, None)
    assert parse_rir("") == (None, None)
    for bad in ("x", "1-2-3", "12"):
        with pytest.raises(ValueError):
            parse_rir(bad)


def test_the_form_reads_rir_ranges_and_warmups(day, athlete, gym):
    rx = program_services.add_prescription(day, ex(gym, "bsq"), athlete)
    form = PrescriptionForm(
        post(sets="3", rep_scheme="10-12", load_basis="none", rir="1-2", note=""), unit="kg"
    )
    assert form.is_valid(), form.errors
    form.save(rx)
    rx.refresh_from_db()
    assert (rx.reps, rx.rir, rx.rir_max) == (10, 1, 2)
    assert summary(rx, "kg") == "3×10-12 · RIR 1–2"
    assert PrescriptionForm.initial_for(rx, "kg")["rir"] == "1–2"
    assert parse_rir(PrescriptionForm.initial_for(rx, "kg")["rir"]) == (1, 2)  # the en dash reads back

    bad = PrescriptionForm(post(sets="3", load_basis="none", rir="lots"), unit="kg")
    assert not bad.is_valid() and "rir" in bad.errors

    warm = PrescriptionForm(
        post(
            sets="4",
            rep_scheme="x 5 breaths",
            load_basis="percent",
            load_value="70",
            rir="2",
            warmup="on",
            section="Strength",
            superset="on",
        ),
        unit="kg",
    )
    assert warm.is_valid(), warm.errors
    warm.save(rx)
    rx.refresh_from_db()
    assert rx.warmup and rx.sets == 1 and rx.load_basis == LoadBasis.NONE and rx.rir is None
    assert (rx.section, rx.superset) == ("", False)
    assert summary(rx, "kg") == "x 5 breaths"


# ---------------------------------------------------------------- layout on the board


def test_warmups_stay_first_and_supersets_are_labelled(day, athlete, gym, drill):
    squat = program_services.add_prescription(day, ex(gym, "bsq"), athlete)
    rdl = program_services.add_prescription(day, ex(gym, "rdl"), athlete)
    row = program_services.add_prescription(day, ex(gym, "row"), athlete)
    warm = program_services.add_prescription(day, drill, athlete)  # added last, lands first
    session = day.sessions.get()
    assert [rx.pk for rx in session.prescriptions.all()] == [warm.pk, squat.pk, rdl.pk, row.pk]
    assert warm.warmup and warm.sets == 1  # a warm-up drill starts as one, with no sets to log

    # Dragging a lift above the warm-up still leaves the warm-up first.
    program_services.move_prescription(row, session, 0)
    assert list(session.prescriptions.values_list("pk", flat=True))[0] == warm.pk

    dose(squat, section="Strength")
    dose(rdl, section="Hypertrophy", section_note="Superset when you can")
    dose(row, superset=True)
    # The row was dragged to the top, so it has nothing above it to superset with yet.
    warmups, entries = layout(session.prescriptions.all())
    assert warmups == [warm]
    assert [(e["item"].pk, e["label"], e["section"]) for e in entries] == [
        (row.pk, "", ""),
        (squat.pk, "", "Strength"),
        (rdl.pk, "", "Hypertrophy"),
    ]
    program_services.move_prescription(row, session, 3)  # back after the RDL
    warmups, entries = layout(session.prescriptions.all())
    assert [(e["item"].pk, e["label"]) for e in entries] == [(squat.pk, ""), (rdl.pk, "B1"), (row.pk, "B2")]


def test_board_shows_warmup_sections_and_superset_labels(coach_client, day, athlete, gym, drill):
    program_services.add_prescription(day, drill, athlete)
    squat = program_services.add_prescription(day, ex(gym, "bsq"), athlete)
    rdl = program_services.add_prescription(day, ex(gym, "rdl"), athlete)
    row = program_services.add_prescription(day, ex(gym, "row"), athlete)
    dose(squat, section="Strength")
    dose(rdl, section="Hypertrophy", section_note="Superset non-competing exercises")
    dose(row, superset=True)
    html = coach_client.get(reverse("coach:program", args=[athlete.pk])).content.decode()
    for text in [
        "<b>Warm-up</b>",
        "<b>Strength</b>",
        "<b>Hypertrophy</b>",
        "Superset non-competing exercises",
        '<span class="ss">B1</span>',
        '<span class="ss">B2</span>',
        "rx-item warm",
    ]:
        assert text in html, text


def test_editing_through_the_modal_moves_a_new_warmup_up(coach_client, day, athlete, gym):
    squat = program_services.add_prescription(day, ex(gym, "bsq"), athlete)
    mob = program_services.add_prescription(day, ex(gym, "mob"), athlete)
    response = coach_client.post(
        reverse("coach:rx_edit", args=[athlete.pk, mob.pk]),
        {"sets": "1", "rep_scheme": "5 min", "load_basis": "none", "warmup": "on"},
        **HX,
    )
    assert response.status_code == 200
    assert list(day.sessions.get().prescriptions.values_list("pk", flat=True)) == [mob.pk, squat.pk]


def test_layout_is_copied_through_templates_and_undo(coach, athlete, day, gym, drill):
    squat = program_services.add_prescription(day, ex(gym, "bsq"), athlete)
    program_services.add_prescription(day, drill, athlete)
    dose(squat, section="Strength", section_note="Heavy", rir=1, rir_max=2, rep_scheme="5-6", reps=5)
    template = library_services.save_program(gym, coach.user, day.week.program, "Meso copy")
    slots = list(template.weeks.get().sessions.get().slots.all())
    assert [s.warmup for s in slots] == [True, False]
    assert (slots[1].section, slots[1].section_note, slots[1].rir, slots[1].rir_max) == (
        "Strength",
        "Heavy",
        1,
        2,
    )

    week = day.week
    undo.record(week, coach.user, "Edit squat")
    dose(squat, section="", rir_max=None, superset=True)
    undo.undo(week)
    squat.refresh_from_db()
    assert (squat.section, squat.rir_max, squat.superset) == ("Strength", 2, False)


# ---------------------------------------------------------------- the player


@pytest.fixture
def log(day, athlete, gym, drill):
    squat = program_services.add_prescription(day, ex(gym, "bsq"), athlete)
    program_services.add_prescription(day, drill, athlete)
    rdl = program_services.add_prescription(day, ex(gym, "rdl"), athlete)
    row = program_services.add_prescription(day, ex(gym, "row"), athlete)
    dose(squat, section="Strength", rir=1, rir_max=2)
    dose(rdl, section="Hypertrophy", rep_scheme="10-12", reps=10)
    dose(row, superset=True)
    return sessions.start(athlete, day.sessions.get())


def test_steps_are_warmup_then_exercises_with_supersets_together(log):
    steps = sessions.steps(log.exercises.all())
    assert [s["warmup"] for s in steps] == [True, False, False]
    assert [se.exercise_name for se in steps[0]["items"]] == ["Deep Squat Lat Hang"]
    assert [se.exercise_name for se in steps[2]["items"]] == ["Romanian Deadlift", "Pendlay Row"]
    assert steps[2]["labels"] == ["B1", "B2"] and steps[2]["section"] == "Hypertrophy"
    assert log.name == "Back Squat + Romanian Deadlift + 1 more"  # warm-ups don't name the session
    assert sessions.planned_sets(log.exercises.get(warmup=True)) == 0


def test_warmup_checklist_links_demos_and_ticks(athlete_client, log):
    page = athlete_client.get(reverse("app:player", args=[log.pk, 1])).content.decode()
    assert "<h1>Warm-up</h1>" in page and 'href="https://www.youtube.com/watch?v=abc"' in page
    se = log.exercises.get(warmup=True)
    response = athlete_client.post(reverse("app:warmup_check", args=[log.pk, se.pk]), {"checked": "1"}, **HX)
    assert "wu-item done" in response.content.decode()
    se.refresh_from_db()
    assert se.checked_at is not None
    athlete_client.post(reverse("app:warmup_check", args=[log.pk, se.pk]), {"checked": "0"}, **HX)
    se.refresh_from_db()
    assert se.checked_at is None


def test_superset_screen_and_banner(athlete_client, log):
    squat = athlete_client.get(reverse("app:player", args=[log.pk, 2])).content.decode()
    assert "Strength" in squat and "RIR 1–2" in squat and "Start lifting" not in squat
    superset = athlete_client.get(reverse("app:player", args=[log.pk, 3])).content.decode()
    assert "Superset — alternate between these" in superset
    assert 'aria-label="B1 Set 1 reps"' in superset and 'aria-label="B2 Set 1 reps"' in superset
    assert 'placeholder="10-12"' in superset and 'data-reps="10"' in superset
    assert "Finish session →" in superset


def test_resume_skips_the_warmup_once_lifting(athlete_client, log, athlete):
    log.checkin_skipped = True
    log.save()
    assert athlete_client.get(reverse("app:resume", args=[log.pk]))["Location"].endswith("/exercise/1/")
    squat = log.exercises.get(exercise_name="Back Squat")
    sessions.save_set(squat, 1, load_kg=Decimal(100), reps=5, duration_seconds=None, rir=2, done=True)
    assert athlete_client.get(reverse("app:resume", args=[log.pk]))["Location"].endswith("/exercise/2/")


def test_warmups_are_not_counted_as_sets(coach, athlete, log):
    for se in log.exercises.filter(warmup=False):
        for n in range(1, 4):
            sessions.save_set(se, n, load_kg=Decimal(60), reps=5, duration_seconds=None, rir=None, done=True)
    sessions.finish(log, 7, "")
    client = Client()
    client.force_login(athlete.user)
    done = client.get(reverse("app:done", args=[log.pk])).content.decode()
    assert "9/9" in done
    coach_client = Client()
    coach_client.force_login(coach.user)
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/sessions/").content.decode()
    assert "0/1 drills ticked" in html and "3 exercises" in html


# ---------------------------------------------------------------- check-in


def test_short_answer_and_follow_up_questions(athlete_client, athlete, log):
    CheckinQuestion.objects.for_athlete(athlete).delete()
    sore = CheckinQuestion.objects.create(
        athlete=athlete, order=0, type=QuestionType.SCALE, text="Soreness level", detail_label="Where?"
    )
    CheckinQuestion.objects.create(athlete=athlete, order=1, type=QuestionType.TEXT, text="Other notes")
    page = athlete_client.get(reverse("app:checkin", args=[log.pk, 1])).content.decode()
    assert "Where?" in page
    athlete_client.post(reverse("app:checkin", args=[log.pk, 1]), {"value": "8", "other_text": "thighs"})
    page = athlete_client.get(reverse("app:checkin", args=[log.pk, 2])).content.decode()
    assert 'name="value"' in page and "leave it empty" in page
    response = athlete_client.post(reverse("app:checkin", args=[log.pk, 2]), {"value": ""})
    assert response["Location"].endswith("/checkin/done/")  # an empty short answer is fine
    answers = {a.question_text: a for a in CheckinAnswer.objects.filter(session_log=log)}
    assert (answers["Soreness level"].value, answers["Soreness level"].other_text) == ("8", "thighs")
    assert answers["Other notes"].display == "—"
    summary_page = athlete_client.get(reverse("app:checkin_summary", args=[log.pk])).content.decode()
    assert "8 / 10 · thighs" in summary_page
    assert sore.copy_for(athlete).detail_label == "Where?"


def test_builder_adds_short_answers_and_saves_follow_ups(coach_client, athlete):
    base = f"/coach/athletes/{athlete.pk}/questions/"
    html = coach_client.post(base + "add/text/", **HX).content.decode()
    assert "short answer" in html
    scale = CheckinQuestion.objects.create(athlete=athlete, order=5, type=QuestionType.SCALE, text="Sore?")
    coach_client.post(
        base + f"{scale.pk}/update/",
        {f"text_{scale.pk}": "Sore?", f"detail_label_{scale.pk}": "Where?"},
        **HX,
    )
    scale.refresh_from_db()
    assert scale.detail_label == "Where?"


# ---------------------------------------------------------------- program notes


def test_program_note_is_edited_on_the_board_and_shown_to_the_athlete(coach_client, athlete, day):
    response = coach_client.post(
        reverse("coach:program_note", args=[athlete.pk]), {"note": "Rest as needed."}, **HX
    )
    assert json.loads(response["HX-Trigger"])["toast"]["message"] == "Program note saved"
    client = Client()
    client.force_login(athlete.user)
    assert "Rest as needed." in client.get(reverse("app:home")).content.decode()
    assert "Rest as needed." in client.get(reverse("app:progress")).content.decode()


def test_template_note_becomes_the_program_note(coach, athlete, gym):
    template = library_services.new_template(gym, TemplateKind.PROGRAM, coach.user)
    template.program_note = "Goal: strong and healthy."
    template.save()
    session = template.weeks.get().sessions.first()
    library_services.add_slot(session, ex(gym, "bsq"))
    program, _first, _habits = apply.confirm(
        athlete, template, [0, 2, 4], apply.DEFAULTS, "new:this", True, coach.user
    )
    assert program.note == "Goal: strong and healthy."


def test_template_editor_saves_the_note(coach_client, coach, gym):
    template = library_services.new_template(gym, TemplateKind.PROGRAM, coach.user)
    coach_client.post(reverse("coach:template_meta", args=[template.pk]), {"program_note": "Eat well."}, **HX)
    template.refresh_from_db()
    assert template.program_note == "Eat well."


# ---------------------------------------------------------------- the demo athlete


def test_seed_has_the_client_style_program():
    from apps.accounts.models import Athlete

    call_command("seed_demo")
    riley = Athlete.objects.get(user__email="riley@ironridge.example")
    assert riley.units == "lb"
    program = riley.programs.active().get()
    assert "Rest as needed" in program.note and program.weeks.count() == 4
    template = Template.objects.get(name="Meso 1 — Powerbuilding")
    first = template.weeks.first().sessions.first().slots.all()
    assert [s.warmup for s in first][:6] == [True] * 6
    squat = next(s for s in first if s.exercise.name == "Back Squat")
    assert squat.load_basis == LoadBasis.RPE and [o.load_value for o in squat.set_overrides.all()] == [
        8,
        9,
        7,
    ]
    logs = riley.session_logs.finished()
    assert logs.count() >= 7  # weeks 1-2 at least, less week 1's Day 4
    warm = logs.first().exercises.filter(warmup=True)
    assert not warm.exists() or all(se.checked_at for se in warm)
    assert CheckinAnswer.objects.filter(session_log__athlete=riley, other_text="thighs").exists()


def test_template_slots_take_warmups_and_sections(coach_client, coach, gym):
    template = library_services.new_template(gym, TemplateKind.PROGRAM, coach.user)
    session = template.weeks.get().sessions.first()
    squat = library_services.add_slot(session, ex(gym, "bsq"))
    mob = library_services.add_slot(session, ex(gym, "mob"))
    response = coach_client.post(
        reverse("coach:template_slot_edit", args=[template.pk, mob.pk]),
        {
            "kind": "exercise",
            "exercise": mob.exercise_id,
            "sets": "1",
            "rep_scheme": "5 min",
            "load_basis": "none",
            "warmup": "on",
        },
        **HX,
    )
    assert response.status_code == 200
    assert list(session.slots.values_list("pk", flat=True)) == [mob.pk, squat.pk]
    html = coach_client.get(reverse("coach:template_edit", args=[template.pk])).content.decode()
    assert "<b>Warm-up</b>" in html and "rx-item warm" in html
