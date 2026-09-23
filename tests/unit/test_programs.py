import datetime
import json
from decimal import Decimal

import pytest

from apps.accounts.models import Athlete, Coach, Gym, MaxEntry
from apps.exercises.models import Exercise, Tag
from apps.exercises.starter import install_pack
from apps.programs import services
from apps.programs.models import LoadBasis, PrescribedSet, Prescription, Program, ProgramSession, WeekType
from apps.programs.prescriptions import default_dose, load_text, parse_rep_scheme, suggested_weight, summary

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}
MON = datetime.date(2026, 9, 21)  # a Monday


def ex(gym, key):
    return Exercise.objects.get(gym=gym, key=key)


def wt(gym, name="Accumulation"):
    return WeekType.objects.get(gym=gym, name=name)


@pytest.fixture
def program(athlete, coach):
    return services.start_program(
        athlete, "Comp Prep", MON + datetime.timedelta(days=2), 3, wt(coach.gym), by=coach.user
    )


def toast(response):
    return json.loads(response["HX-Trigger"])["toast"]["message"]


def base(athlete):
    return f"/coach/athletes/{athlete.pk}/program/"


# ---------------------------------------------------------------- parsing and display


@pytest.mark.parametrize(
    "text,expected",
    [
        ("5", (5, None)),
        ("1+1", (1, None)),
        ("2 + 1 + 1", (1, None)),
        ("8/leg", (8, None)),
        ("10 each", (10, None)),
        ("12 per arm", (12, None)),
        ("10 min", (None, 600)),
        ("30s", (None, 30)),
        ("1.5 min", (None, 90)),
        ("AMRAP", (None, None)),
        ("20 m", (None, None)),
        ("400m", (None, None)),
        ("5-3-1", (None, None)),
        ("", (None, None)),
    ],
)
def test_parse_rep_scheme(text, expected):
    assert parse_rep_scheme(text) == expected


def test_load_text():
    assert load_text(LoadBasis.PERCENT, Decimal("75.00"), "kg") == "75%"
    assert load_text(LoadBasis.RPE, Decimal("8"), "kg") == "RPE 8"
    assert load_text(LoadBasis.WEIGHT, Decimal("100"), "lb") == "220.5 lb"
    assert load_text(LoadBasis.BODYWEIGHT, None, "kg") == "BW"
    assert load_text(LoadBasis.NONE, Decimal("5"), "kg") == ""


def test_summary_and_suggested_weight(athlete, program, gym):
    day = program.weeks.first().days.first()
    rx = services.add_prescription(day, ex(gym, "fsq"), athlete)
    rx.sets, rx.rep_scheme, rx.load_basis, rx.load_value, rx.rir = 5, "3", LoadBasis.PERCENT, Decimal("80"), 2
    rx.custom_fields = [{"key": "Tempo", "value": "3-1-0"}]
    rx.save()
    assert summary(rx, "kg") == "5×3 @ 80% · RIR 2 · Tempo 3-1-0"
    assert suggested_weight(rx, athlete, "kg") is None  # no back squat max yet
    MaxEntry.objects.create(athlete=athlete, exercise=ex(gym, "bsq"), date=MON, kg=150, source="coach")
    assert suggested_weight(rx, athlete, "kg") == "≈ 120 kg of Back Squat max 150 kg"
    PrescribedSet.objects.bulk_create(
        [
            PrescribedSet(prescription=rx, set_number=i, rep_scheme="3", load_value=v)
            for i, v in [(1, 70), (2, 75), (3, 80)]
        ]
    )
    assert summary(rx, "kg").startswith("3 sets: 3@70%, 3@75%, 3@80%")


def test_default_dose_copies_last_time_or_uses_the_measure(athlete, program, gym):
    days = list(program.weeks.first().days.all())
    assert default_dose(ex(gym, "bike"), athlete)["rep_scheme"] == "10 min"
    assert default_dose(ex(gym, "bike"), athlete)["duration_seconds"] == 600
    first = services.add_prescription(days[0], ex(gym, "sn"), athlete)
    assert (first.sets, first.rep_scheme, first.reps) == (3, "5", 5)
    first.sets, first.rep_scheme, first.load_basis, first.load_value = 6, "2", LoadBasis.PERCENT, 78
    first.save()
    again = services.add_prescription(days[2], ex(gym, "sn"), athlete)
    assert (again.sets, again.rep_scheme, again.load_value) == (6, "2", Decimal("78.00"))


# ---------------------------------------------------------------- program structure


def test_start_program_snaps_to_the_week_start_and_makes_back_to_back_weeks(program):
    weeks = list(program.weeks.all())
    assert program.start_date == MON
    assert [w.start_date for w in weeks] == [MON, MON + datetime.timedelta(7), MON + datetime.timedelta(14)]
    assert all(w.days.count() == 7 for w in weeks)
    assert list(weeks[1].days.values_list("date", flat=True))[0] == MON + datetime.timedelta(7)
    assert not any(w.published for w in weeks)


def test_sunday_gyms_start_weeks_on_sunday(athlete, coach):
    coach.gym.week_start = 6
    coach.gym.save()
    athlete.refresh_from_db()
    p = services.start_program(
        athlete, "Block", MON + datetime.timedelta(days=2), 1, wt(coach.gym), by=coach.user
    )
    assert p.start_date == datetime.date(2026, 9, 20)  # the Sunday before
    assert p.start_date.weekday() == 6


def test_starting_a_new_program_ends_the_old_one(athlete, coach, program):
    new = services.start_program(athlete, "Next", MON, 1, wt(coach.gym), by=coach.user)
    program.refresh_from_db()
    assert not program.active and program.ended_at is not None and new.active
    assert Program.objects.filter(athlete=athlete).count() == 2


def test_duplicate_inserts_after_and_shifts_later_weeks(athlete, gym, program):
    w1, w2, w3 = program.weeks.all()
    day = w1.days.first()
    rx = services.add_prescription(day, ex(gym, "sn"), athlete)
    rx.custom_fields = [{"key": "Rest", "value": "3 min"}]
    rx.save()
    rx.tag_slot_tags.add(Tag.objects.get(gym=gym, name="speed"))
    PrescribedSet.objects.create(prescription=rx, set_number=1, rep_scheme="2", load_value=70)
    services.add_session(day, "PM")
    w1.focus_note, w1.published = "Stay crisp", True
    w1.save()

    copy = services.duplicate_week(w1)
    weeks = list(program.weeks.all())
    assert [w.pk for w in weeks] == [w1.pk, copy.pk, w2.pk, w3.pk]
    assert [w.order for w in weeks] == [0, 1, 2, 3]
    assert [w.start_date for w in weeks] == [MON + datetime.timedelta(7 * i) for i in range(4)]
    w3.refresh_from_db()
    assert list(w3.days.values_list("date", flat=True))[0] == MON + datetime.timedelta(21)  # days moved too
    assert not copy.published and copy.focus_note == "Stay crisp"
    copied = Prescription.objects.get(session__day__week=copy)
    assert copied.custom_fields == [{"key": "Rest", "value": "3 min"}]
    assert list(copied.tag_slot_tags.values_list("name", flat=True)) == ["speed"]
    assert copied.set_overrides.get().load_value == 70
    assert copied.session.day.date == MON + datetime.timedelta(7)
    assert ProgramSession.objects.filter(day__week=copy, name="PM").exists()
    assert Prescription.objects.filter(session__day__week=w1).count() == 1  # original untouched


def test_delete_week_closes_the_gap(program):
    w1, w2, w3 = program.weeks.all()
    services.delete_week(w2)
    w3.refresh_from_db()
    assert (w3.order, w3.start_date) == (1, MON + datetime.timedelta(7))
    assert list(w3.days.values_list("date", flat=True))[0] == MON + datetime.timedelta(7)


def test_add_week_continues_the_dates(program, coach):
    week = services.add_week(program, wt(coach.gym, "Deload"))
    assert (week.order, week.start_date, week.week_type.name) == (3, MON + datetime.timedelta(21), "Deload")


def test_move_and_remove_keep_orders_tidy(athlete, gym, program):
    d1, d2 = list(program.weeks.first().days.all())[:2]
    a, b, c = (services.add_prescription(d1, ex(gym, k), athlete) for k in ["sn", "snp", "bsq"])
    services.move_prescription(c, a.session, 0)
    assert list(a.session.prescriptions.values_list("exercise__key", flat=True)) == ["bsq", "sn", "snp"]
    target = services.session_for(d2)
    services.move_prescription(a, target, 0)
    assert list(target.prescriptions.values_list("exercise__key", flat=True)) == ["sn"]
    assert list(c.session.prescriptions.values_list("order", flat=True)) == [0, 1]
    services.remove_prescription(a)
    assert not ProgramSession.objects.filter(pk=target.pk).exists()  # empty unnamed session goes


def test_one_active_program_per_athlete(athlete, program):
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        Program.objects.create(athlete=athlete, name="Dup", start_date=MON)


# ---------------------------------------------------------------- the editor, over HTTP


def test_program_tab_offers_to_start_one(coach_client, athlete):
    html = coach_client.get(base(athlete)).content.decode()
    assert "Start a program for Maya" in html and "Starts the week of" in html


def test_start_program_form(coach_client, athlete, gym):
    response = coach_client.post(
        f"{base(athlete)}start/",
        {"name": "Block A", "first_day": "2026-09-23", "weeks": "2", "week_type": wt(gym).pk},
        **HX,
    )
    assert response["HX-Redirect"] == base(athlete)
    program = athlete.programs.active().get()
    assert (program.name, program.start_date, program.weeks.count()) == ("Block A", MON, 2)
    assert "Start a new program" in coach_client.get(base(athlete)).content.decode()
    modal = coach_client.get(f"{base(athlete)}start/", **HX).content.decode()
    assert "Starting a new program ends the current one" in modal
    html = coach_client.post(
        f"{base(athlete)}start/", {"name": "", "first_day": "", "weeks": "99", "week_type": wt(gym).pk}, **HX
    ).content.decode()
    assert html.count("errorlist") >= 2 and 'id="startProgramForm"' in html
    assert athlete.programs.count() == 1


def test_editor_shows_the_current_week(coach_client, athlete, program, monkeypatch):
    monkeypatch.setattr(Athlete, "today", lambda self: MON + datetime.timedelta(days=9))
    html = coach_client.get(base(athlete)).content.decode()
    assert "Wk 2 · Mon 28 Sep–Sun 4 Oct" in html and "this week" in html
    w3 = program.weeks.get(order=2)
    assert "Wk 3 · Mon 5 Oct" in coach_client.get(f"{base(athlete)}?week={w3.pk}").content.decode()


def test_add_exercise_needs_a_selected_day(coach_client, athlete, program, gym):
    response = coach_client.post(f"{base(athlete)}add/", {"exercise": ex(gym, "sn").pk, "day": ""}, **HX)
    assert toast(response) == "Click a day on the board first"
    assert response["HX-Reswap"] == "none" and "HX-Retarget" not in response
    day = program.weeks.first().days.first()
    response = coach_client.post(f"{base(athlete)}add/", {"exercise": ex(gym, "sn").pk, "day": day.pk}, **HX)
    assert toast(response) == "Snatch → Mon 21 Sep" and "HX-Retarget" not in response
    assert "3×5" in response.content.decode()


def test_library_search_and_tags(coach_client, athlete, program, gym):
    html = coach_client.get(f"{base(athlete)}library/", {"q": "squat"}, **HX).content.decode()
    assert "Front Squat" in html and "Power Clean" not in html
    assert f'hx-post="{base(athlete)}add/"' in html
    speed = Tag.objects.get(gym=gym, name="speed")
    html = coach_client.get(f"{base(athlete)}library/", {"tag": [speed.pk]}, **HX).content.decode()
    assert "Power Snatch" in html and "Back Squat" not in html


def test_week_actions(coach_client, athlete, program, gym):
    w1 = program.weeks.first()
    r = coach_client.post(f"{base(athlete)}weeks/{w1.pk}/publish/", {"publish": "1"}, **HX)
    assert "Maya sees it now" in toast(r)
    w1.refresh_from_db()
    assert w1.published and w1.published_at
    assert "Live — Maya sees edits immediately" in r.content.decode()
    r = coach_client.post(
        f"{base(athlete)}weeks/{w1.pk}/settings/", {"week_type": wt(gym, "Deload").pk}, **HX
    )
    assert toast(r) == "Wk 1 is now Deload"
    r = coach_client.post(
        f"{base(athlete)}weeks/{w1.pk}/settings/", {"focus_note": " Openers Saturday "}, **HX
    )
    w1.refresh_from_db()
    assert w1.focus_note == "Openers Saturday" and toast(r) == "Focus note saved"
    r = coach_client.post(f"{base(athlete)}weeks/{w1.pk}/duplicate/", **HX)
    assert "later weeks moved back a week" in toast(r)
    r = coach_client.post(f"{base(athlete)}weeks/add/", **HX)
    assert "Wk 5 added at the end" in toast(r)
    last = program.weeks.last()
    assert toast(coach_client.post(f"{base(athlete)}weeks/{last.pk}/delete/", **HX)).startswith(
        "Deleted Wk 5"
    )
    services.add_prescription(w1.days.first(), ex(gym, "sn"), athlete)
    assert toast(coach_client.post(f"{base(athlete)}weeks/{w1.pk}/clear/", **HX)) == "Week cleared"
    assert not ProgramSession.objects.filter(day__week=w1).exists()
    r = coach_client.post(f"{base(athlete)}weeks/{w1.pk}/publish/", {"publish": "0"}, **HX)
    assert "no longer sees it" in toast(r)


def test_archived_week_types_cannot_be_newly_chosen(coach_client, athlete, program, gym):
    cutting = wt(gym, "Cutting")
    cutting.archived = True
    cutting.save()
    w1 = program.weeks.first()
    assert (
        coach_client.post(
            f"{base(athlete)}weeks/{w1.pk}/settings/", {"week_type": cutting.pk}, **HX
        ).status_code
        == 404
    )


def test_used_week_types_are_archived_not_deleted(coach_client, program, gym):
    accumulation = wt(gym)
    r = coach_client.post(f"/coach/settings/week-types/{accumulation.pk}/remove/", **HX)
    assert "used by 3 weeks, so it was archived" in toast(r)
    accumulation.refresh_from_db()
    assert accumulation.archived and program.weeks.first().week_type == accumulation


def test_sessions(coach_client, athlete, program, gym):
    day = program.weeks.first().days.first()
    services.add_prescription(day, ex(gym, "sn"), athlete)
    coach_client.post(f"{base(athlete)}days/{day.pk}/sessions/add/", **HX)
    names = list(day.sessions.values_list("name", flat=True))
    assert names == ["Session 1", "Session 2"]
    s2 = day.sessions.last()
    coach_client.post(f"{base(athlete)}sessions/{s2.pk}/rename/", {f"name_{s2.pk}": "Evening"}, **HX)
    s2.refresh_from_db()
    assert s2.name == "Evening"
    r = coach_client.post(f"{base(athlete)}sessions/{s2.pk}/delete/", **HX)
    assert toast(r) == "Removed the session" and day.sessions.count() == 1


def test_edit_prescription_modal(coach_client, athlete, program, gym):
    gym.units = "lb"
    gym.save()
    day = program.weeks.first().days.first()
    rx = services.add_prescription(day, ex(gym, "rdl"), athlete)
    html = coach_client.get(f"{base(athlete)}rx/{rx.pk}/", **HX).content.decode()
    assert "Romanian Deadlift — Monday 21 Sep" in html and "Vary by set" in html
    r = coach_client.post(
        f"{base(athlete)}rx/{rx.pk}/",
        {
            "sets": "3",
            "rep_scheme": "8",
            "load_basis": "weight",
            "load_value": "225",
            "rir": "2",
            "note": "Slow",
            "cf_key": ["Tempo", ""],
            "cf_value": ["3-1-0", "ignored"],
            "vary": "on",
            "set_reps": ["8", "8", "6"],
            "set_load": ["205", "215", "225"],
        },
        **HX,
    )
    assert r["HX-Retarget"] == "#programEditor" and json.loads(r["HX-Trigger-After-Swap"]) == {
        "closeModal": True
    }
    rx.refresh_from_db()
    assert (rx.sets, rx.reps, rx.load_basis, rx.load_value, rx.rir) == (3, 8, "weight", Decimal("102.06"), 2)
    assert rx.custom_fields == [{"key": "Tempo", "value": "3-1-0"}]
    assert list(rx.set_overrides.values_list("load_value", flat=True)) == [
        Decimal("92.99"),
        Decimal("97.52"),
        Decimal("102.06"),
    ]
    assert "3 sets: 8@205 lb, 8@215 lb, 6@225 lb" in r.content.decode()


@pytest.mark.parametrize(
    "data,error",
    [
        ({"load_basis": "percent", "load_value": ""}, "enter a percentage"),
        ({"load_basis": "rpe", "load_value": "11"}, "an RPE between 1 and 10"),
        (
            {
                "load_basis": "percent",
                "load_value": "80",
                "vary": "on",
                "set_reps": ["5"],
                "set_load": ["80"],
            },
            "Fill in a row for every set.",
        ),
        ({"sets": "0"}, "greater than or equal to 1"),
    ],
)
def test_prescription_validation(coach_client, athlete, program, gym, data, error):
    rx = services.add_prescription(program.weeks.first().days.first(), ex(gym, "sn"), athlete)
    payload = {
        "sets": "3",
        "rep_scheme": "2",
        "load_basis": "none",
        "load_value": "",
        "rir": "",
        "note": "",
        **data,
    }
    html = coach_client.post(f"{base(athlete)}rx/{rx.pk}/", payload, **HX).content.decode()
    assert error in html and 'class="modal open"' in html
    rx.refresh_from_db()
    assert (rx.sets, rx.rep_scheme) == (3, "5")


def test_swap_offers_category_or_tag_matches_and_keeps_the_dose(coach_client, athlete, program, gym):
    rx = services.add_prescription(program.weeks.first().days.first(), ex(gym, "fsq"), athlete)
    rx.sets, rx.rep_scheme = 5, "3"
    rx.save()
    html = coach_client.get(f"{base(athlete)}rx/{rx.pk}/swap/", **HX).content.decode()
    assert "Back Squat" in html and "Overhead Squat" in html and "Ab Wheel" not in html
    r = coach_client.post(f"{base(athlete)}rx/{rx.pk}/swap/", {"exercise": ex(gym, "bsq").pk}, **HX)
    assert toast(r) == "Swapped Front Squat for Back Squat — kept 5×3"
    rx.refresh_from_db()
    assert rx.exercise.key == "bsq" and (rx.sets, rx.rep_scheme) == (5, "3")
    assert (
        coach_client.post(
            f"{base(athlete)}rx/{rx.pk}/swap/", {"exercise": ex(gym, "abw").pk}, **HX
        ).status_code
        == 404
    )


def test_drag_to_another_day(coach_client, athlete, program, gym):
    d1, d2 = list(program.weeks.first().days.all())[:2]
    rx = services.add_prescription(d1, ex(gym, "sn"), athlete)
    coach_client.post(f"{base(athlete)}rx/{rx.pk}/move/", {"session": "", "day": d2.pk, "index": "0"}, **HX)
    rx.refresh_from_db()
    assert rx.session.day == d2 and not d1.sessions.exists()


def test_remove_prescription(coach_client, athlete, program, gym):
    rx = services.add_prescription(program.weeks.first().days.first(), ex(gym, "sn"), athlete)
    r = coach_client.post(f"{base(athlete)}rx/{rx.pk}/remove/", **HX)
    assert toast(r) == "Removed Snatch from Mon" and not Prescription.objects.exists()


def test_everything_is_scoped_to_your_own_athlete(coach_client, athlete, program, gym, make_user):
    other_gym = Gym.objects.create(name="Elsewhere")
    install_pack(other_gym, "weightlifting")
    other_coach = Coach.objects.create(user=make_user("c2@example.com"), gym=other_gym)
    other = Athlete.objects.create(user=make_user("o@example.com", "Other"), coach=other_coach, gym=other_gym)
    theirs = services.start_program(
        other, "Theirs", MON, 1, WeekType.objects.filter(gym=other_gym).first(), by=other_coach.user
    )
    w, d = theirs.weeks.first(), theirs.weeks.first().days.first()
    rx = services.add_prescription(d, ex(other_gym, "sn"), other)
    mine = base(athlete)
    for url in [
        f"{mine}weeks/{w.pk}/publish/",
        f"{mine}weeks/{w.pk}/delete/",
        f"{mine}rx/{rx.pk}/remove/",
        f"{mine}days/{d.pk}/sessions/add/",
        f"/coach/athletes/{other.pk}/program/weeks/add/",
    ]:
        assert coach_client.post(url, {"publish": "1"}, **HX).status_code == 404, url
    assert (
        coach_client.post(f"{mine}add/", {"day": d.pk, "exercise": ex(gym, "sn").pk}, **HX).status_code == 404
    )
    day = program.weeks.first().days.first()
    assert (
        coach_client.post(
            f"{mine}add/", {"day": day.pk, "exercise": ex(other_gym, "sn").pk}, **HX
        ).status_code
        == 404
    )
    assert Prescription.objects.filter(session__day__week__program=theirs).count() == 1


def test_deleting_an_exercise_warns_about_programs(coach_client, athlete, program, gym):
    snatch = ex(gym, "sn")
    services.add_prescription(program.weeks.first().days.first(), snatch, athlete)
    snatch.archived = True
    snatch.save()
    html = coach_client.get(f"/coach/programming/exercises/{snatch.pk}/delete/", **HX).content.decode()
    assert "1 prescription in the programs of Maya Torres" in html
    coach_client.post(f"/coach/programming/exercises/{snatch.pk}/delete/", **HX)
    assert not Prescription.objects.exists() and not Exercise.objects.filter(pk=snatch.pk).exists()
