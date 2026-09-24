"""Phase 5: templates, saved weeks and sessions, and applying them to an athlete."""

import datetime
import json
from decimal import Decimal

import pytest

from apps.accounts.models import Coach, Gym, Invite
from apps.exercises.deletion import delete_exercise, deletion_impact
from apps.exercises.models import Exercise, Tag
from apps.exercises.starter import install_pack
from apps.library import apply, services
from apps.library.models import SlotKind, Template, TemplateKind, TemplateSlot
from apps.programs import services as program_services
from apps.programs.models import LoadBasis, Prescription, ProgramWeek, WeekType
from apps.workouts import sessions as workout_sessions

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}
DAY = datetime.timedelta(days=1)


def ex(gym, key):
    return Exercise.objects.get(gym=gym, key=key)


def tag(gym, name):
    return Tag.objects.get(gym=gym, name=name)


def toast(response):
    return json.loads(response["HX-Trigger"])["toast"]["message"]


@pytest.fixture
def template(gym, coach):
    """3 sessions a week, two weeks: A (snatch 5×2 @ 70%), B (tag slot [unilateral], default
    Bulgarian split squat), C (C&J); week 2 is week 1 bumped by 2.5 points."""
    t = services.new_template(gym, TemplateKind.PROGRAM, coach.user)
    t.name = "Comp Cycle"
    t.save()
    a, b, c = t.weeks.get().sessions.all()
    s = services.add_slot(a, ex(gym, "sn"))
    s.sets, s.rep_scheme, s.reps, s.load_basis, s.load_value = 5, "2", 2, LoadBasis.PERCENT, Decimal("70")
    s.save()
    services.add_slot(b, ex(gym, "bsp"), tags=[tag(gym, "unilateral")])
    services.add_slot(c, ex(gym, "cj"))
    services.add_week(t, Decimal("2.5"))
    return t


@pytest.fixture
def step_up(gym):
    """A second "unilateral" exercise (the starter pack has only Bulgarian split squats)."""
    bsp = ex(gym, "bsp")
    step = Exercise.objects.create(gym=gym, name="Step-up", category=bsp.category)
    step.tags.set([tag(gym, "unilateral")])
    return step


@pytest.fixture
def program(athlete, coach):
    """Two weeks from this week; this week has a session today."""
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    return program_services.start_program(athlete, "Block", athlete.today(), 2, week_type, by=coach.user)


# ---------------------------------------------------------------- editing


def test_add_week_copies_and_bumps_percentages(template, gym):
    week1, week2 = template.weeks.all()
    slot1 = week1.sessions.first().slots.get()
    slot2 = week2.sessions.first().slots.get()
    assert (slot1.load_value, slot2.load_value) == (Decimal("70.00"), Decimal("72.50"))
    assert slot2.pk != slot1.pk and week2.sessions.count() == 3
    tag_slot = week2.sessions.all()[1].slots.get()
    assert tag_slot.kind == SlotKind.TAG and [t.name for t in tag_slot.tags.all()] == ["unilateral"]


def test_bump_only_touches_percentages():
    assert services.bump(Decimal("8"), LoadBasis.RPE, 2) == Decimal("8")
    assert services.bump(Decimal("100"), LoadBasis.WEIGHT, 2) == Decimal("100")
    assert services.bump(Decimal("70"), LoadBasis.PERCENT, Decimal("-2.5")) == Decimal("67.5")


def test_saving_a_board_week_and_a_program(athlete, coach, gym, program):
    week = program.weeks.first()
    today = athlete.today()
    day = week.days.get(date=today)
    program_services.add_prescription(day, ex(gym, "sn"), athlete)
    saved = services.save_week(gym, coach.user, week, "My week")
    session = saved.weeks.get().sessions.get()
    assert saved.kind == TemplateKind.WEEK and session.name == today.strftime("%A")
    assert session.slots.get().exercise.key == "sn"
    whole = services.save_program(gym, coach.user, program, "From Maya")
    assert whole.kind == TemplateKind.PROGRAM and whole.weeks.count() == 1  # only weeks with work


def test_editor_actions(coach_client, template, gym):
    base = f"/coach/library/{template.pk}/"
    assert "Comp Cycle" in coach_client.get(base).content.decode()
    session = template.weeks.first().sessions.first()
    response = coach_client.post(
        base + "slots/add/", {"exercise": ex(gym, "bsq").pk, "session": session.pk}, **HX
    )
    assert "Back Squat" in toast(response) and session.slots.count() == 2
    assert "Select a session" in toast(
        coach_client.post(base + "slots/add/", {"exercise": ex(gym, "bsq").pk}, **HX)
    )
    response = coach_client.post(
        base + "slots/add-tag/",
        {"session": session.pk, "tag": [tag(gym, "overhead").pk, tag(gym, "strength").pk]},
        **HX,
    )
    assert "Tag slot [overhead, strength]" in toast(response)
    slot = session.slots.last()
    assert slot.kind == SlotKind.TAG and set(slot.exercise.tags.values_list("name", flat=True)) >= {
        "overhead",
        "strength",
    }
    coach_client.post(base + "meta/", {"name": "Renamed", "sessions_per_week": "4"}, **HX)
    template.refresh_from_db()
    assert (template.name, template.sessions_per_week) == ("Renamed", 4)
    coach_client.post(base + f"weeks/{template.weeks.last().pk}/remove/", **HX)
    assert template.weeks.count() == 1


def test_slot_modal_switches_between_fixed_and_tag(coach_client, template, gym):
    slot = template.weeks.first().sessions.first().slots.get()
    url = f"/coach/library/{template.pk}/slots/{slot.pk}/"
    assert "Fixed exercise" in coach_client.get(url).content.decode()
    dose = {"sets": "4", "rep_scheme": "3", "load_basis": "percent", "load_value": "75"}
    bad = coach_client.post(
        url, {**dose, "kind": "tag", "tags": [tag(gym, "overhead").pk], "default": ex(gym, "sn").pk}, **HX
    )
    assert "carries every tag" in bad.content.decode()  # snatch isn't tagged "overhead"
    response = coach_client.post(
        url, {**dose, "kind": "tag", "tags": [tag(gym, "overhead").pk], "default": ex(gym, "pp").pk}, **HX
    )
    assert response["HX-Retarget"] == "#tplEditor"
    slot.refresh_from_db()
    assert (slot.kind, slot.exercise.key, slot.sets, slot.load_value) == ("tag", "pp", 4, Decimal("75"))


def test_saved_weeks_and_sessions_drop_into_templates(coach_client, coach, gym, template):
    first_week = template.weeks.first()
    saved_week = services.save_template_week(gym, coach.user, first_week, "Three day")
    saved_session = services.save_session(gym, coach.user, first_week.sessions.first(), "Snatch day")
    base = f"/coach/library/{template.pk}/"
    assert "Three day" in coach_client.get(base + "pick/week/").content.decode()
    coach_client.post(base + f"pick/week/{saved_week.pk}/", **HX)
    assert template.weeks.count() == 3
    coach_client.post(base + f"pick/session/{saved_session.pk}/", {"week": first_week.pk}, **HX)
    assert first_week.sessions.last().name == "Snatch day" and first_week.sessions.count() == 4


def test_list_pages(coach_client, template):
    html = coach_client.get("/coach/programming/templates/").content.decode()
    assert "Comp Cycle" in html and "2 weeks · 6 sessions · written for 3×/week · 2 tag slots" in html
    assert "No saved weeks yet" in coach_client.get("/coach/programming/weeks/").content.decode()
    response = coach_client.post("/coach/programming/sessions/new/")
    assert Template.objects.get(kind="session").weeks.get().sessions.count() == 1
    assert response["Location"].startswith("/coach/library/")


def test_other_gyms_templates_are_out_of_reach(client, make_user, template):
    other_gym = Gym.objects.create(name="Elsewhere")
    install_pack(other_gym, "weightlifting")
    other = Coach.objects.create(user=make_user("sam@example.com", "Sam"), gym=other_gym)
    client.force_login(other.user)
    assert client.get(f"/coach/library/{template.pk}/").status_code == 404
    assert "Comp Cycle" not in client.get("/coach/programming/templates/").content.decode()


# ---------------------------------------------------------------- planning


def test_plan_packs_sessions_into_the_chosen_days(template, athlete):
    weeks = apply.plan(template, athlete, [0, 2, 4], apply.DEFAULTS)
    assert len(weeks) == 2 and sorted(weeks[0].days) == [0, 2, 4]
    weeks = apply.plan(template, athlete, [0, 3], apply.DEFAULTS)  # 6 sessions at 2 a week
    assert [w.session_count for w in weeks] == [2, 2, 2]
    assert apply.plan(template, athlete, [], apply.DEFAULTS) == []


def test_tag_slots_resolve_to_recent_lifts(template, athlete, gym, program, coach, step_up):
    # Maya did step-ups (unilateral) recently: "recent" mode picks them over the default.
    day = program.weeks.first().days.get(date=athlete.today())
    program_services.add_prescription(day, step_up, athlete)
    for week in program.weeks.all():
        program_services.set_published(week, True)
    log = workout_sessions.start(athlete, day.sessions.get())
    se = log.exercises.get()
    workout_sessions.save_set(
        se, 1, load_kg=Decimal("20"), reps=8, duration_seconds=None, rir=None, done=True
    )
    workout_sessions.finish(log, 7, "")
    recent = apply.plan(template, athlete, [0, 2, 4], apply.RECENT)[0].days[2].exercises[0][1]
    default = apply.plan(template, athlete, [0, 2, 4], apply.DEFAULTS)[0].days[2].exercises[0][1]
    assert recent == step_up and default.key == "bsp"


# ---------------------------------------------------------------- confirming


def test_confirm_appends_unpublished_weeks_with_the_exact_dose(template, athlete, coach, program):
    program_before = program.weeks.count()
    prog, first, _habits = apply.confirm(
        athlete, template, [0, 2, 4], apply.DEFAULTS, "append", False, coach.user
    )
    assert prog == program and first.order == program_before and program.weeks.count() == program_before + 2
    assert not first.published and first.start_date == program.start_date + apply.WEEK * first.order
    rx = Prescription.objects.filter(session__day__week=first, exercise__key="sn").get()
    assert (rx.sets, rx.rep_scheme, rx.load_basis, rx.load_value) == (5, "2", "percent", Decimal("70.00"))
    tagged = Prescription.objects.get(session__day__week=first, exercise__key="bsp")
    assert [t.name for t in tagged.tag_slot_tags.all()] == ["unilateral"]  # stays swappable on the board
    assert template.applications.count() == 1


def test_confirm_as_a_new_program(template, athlete, coach, program):
    new, first, _habits = apply.confirm(
        athlete, template, [0, 2, 4], apply.DEFAULTS, "new:next", True, coach.user
    )
    program.refresh_from_db()
    assert not program.active and new.active and new.name == "Comp Cycle" and new.source_template == template
    assert first.published and first.start_date == athlete.gym.week_start_for(athlete.today()) + apply.WEEK


def test_starting_at_a_future_week_replaces_empties_and_moves_the_rest(
    template, athlete, coach, gym, program
):
    week_type = WeekType.objects.get(gym=gym, name="Accumulation")
    program_services.add_week(program, week_type)  # weeks: this, +1 (empty), +2 (gets work)
    later = program.weeks.get(order=2)
    program_services.add_prescription(later.days.first(), ex(gym, "cj"), athlete)
    empty = program.weeks.get(order=1)
    options = {p.value: p for p in apply.placements(athlete)}
    assert (
        f"at:{empty.pk}" in options and "Start at Wk 2 (empty — replaced)" == options[f"at:{empty.pk}"].label
    )
    apply.confirm(athlete, template, [0, 2, 4], apply.DEFAULTS, f"at:{empty.pk}", False, coach.user)
    assert not ProgramWeek.objects.filter(pk=empty.pk).exists()
    later.refresh_from_db()
    assert (
        later.order == 3 and later.start_date == program.start_date + apply.WEEK * 3
    )  # after the 2 new weeks
    assert later.days.first().date == later.start_date and later.days.first().sessions.exists()


def test_apply_preview_views(coach_client, athlete, template, program):
    base = f"/coach/athletes/{athlete.pk}/program/"
    response = coach_client.post(
        "/coach/programming/apply/", {"template": template.pk, "athlete": athlete.pk}, **HX
    )
    assert response["HX-Redirect"] == base
    html = coach_client.get(base).content.decode()
    assert "Previewing" in html and "wk-tab ghost" in html and "2 new weeks" in html
    html = coach_client.post(base + "apply/", {"days_sent": "1", "day": ["0", "3"]}, **HX).content.decode()
    assert "3 new weeks" in html and "2×/week" in html
    html = coach_client.post(base + "apply/", {"view": "1"}, **HX).content.decode()
    assert "week-board ghost" in html
    assert ProgramWeek.objects.filter(program=program).count() == 2  # nothing written yet
    response = coach_client.post(base + "apply/confirm/", **HX)
    assert "“Comp Cycle” applied — 3 weeks" in toast(response)
    assert ProgramWeek.objects.filter(program=program).count() == 5
    assert "Previewing" not in coach_client.get(base).content.decode()


def test_cancel_changes_nothing(coach_client, athlete, template, program):
    base = f"/coach/athletes/{athlete.pk}/program/"
    coach_client.post(
        base + "apply/start/", {"kind": "program"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="programEditor"
    )
    response = coach_client.post(base + "apply/cancel/", **HX)
    assert "nothing changed" in toast(response) and program.weeks.count() == 2


def test_save_week_and_template_from_the_board(coach_client, athlete, gym, program):
    week = program.weeks.first()
    base = f"/coach/athletes/{athlete.pk}/program/"
    assert "no sessions to save" in toast(coach_client.get(base + f"weeks/{week.pk}/save/", **HX))
    program_services.add_prescription(week.days.first(), ex(gym, "sn"), athlete)
    assert "Save week to library" in coach_client.get(base + f"weeks/{week.pk}/save/", **HX).content.decode()
    response = coach_client.post(base + f"weeks/{week.pk}/save/", {"name": "Snatch week"}, **HX)
    assert (
        "Programming › Weeks" in toast(response)
        and Template.objects.filter(kind="week", name="Snatch week").exists()
    )
    coach_client.post(base + "save/", {"name": "Block copy"}, **HX)
    assert Template.objects.filter(kind="program", name="Block copy").exists()


# ---------------------------------------------------------------- invites and deleting


def test_invite_with_a_starting_template_makes_a_draft_program(client, coach, template):
    invite = Invite.objects.create(coach=coach, starting_template=template)
    client.post(
        f"/join/{invite.token}/",
        {
            "name": "Priya",
            "email": "priya@example.com",
            "password": "correct-horse-battery-9",
            "browser_timezone": "",
        },
    )
    athlete = invite.coach.athletes.get(user__email="priya@example.com")
    program = athlete.programs.active().get()
    assert program.name == "Comp Cycle" and program.weeks.count() == 2
    assert not program.weeks.filter(published=True).exists()
    assert program.start_date == athlete.gym.week_start_for(athlete.today()) + apply.WEEK


def test_invite_form_offers_templates(coach_client, template):
    assert "Comp Cycle" in coach_client.get("/coach/invites/new/", **HX).content.decode()


def test_deleting_an_exercise_updates_template_slots(template, gym, step_up):
    bsp = ex(gym, "bsp")
    sn = ex(gym, "sn")
    for e in (bsp, sn):
        e.archived = True
        e.save()
    impact = deletion_impact(bsp)
    assert impact["slots_redefaulted"] == 2 and impact["templates"] == ["Comp Cycle"]  # tag slot, both weeks
    delete_exercise(bsp)
    tag_slots = TemplateSlot.objects.filter(kind=SlotKind.TAG)
    assert tag_slots.count() == 2 and all(s.exercise == step_up for s in tag_slots)
    assert deletion_impact(sn)["slots_removed"] == 2
    delete_exercise(sn)
    assert not TemplateSlot.objects.filter(exercise__key="sn").exists()
