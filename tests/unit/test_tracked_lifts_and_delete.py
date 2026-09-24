import json
from decimal import Decimal

import pytest

from apps.accounts.metrics import metric_specs, save_metrics
from apps.accounts.models import Coach, Gym, MaxEntry
from apps.exercises.models import MAX_TRACKED_LIFTS, Exercise, TrackedLift, tracked_exercises
from apps.exercises.starter import install_pack

from ..conftest import lift_field

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def ex(gym, key):
    return Exercise.objects.get(gym=gym, key=key)


def toast(response):
    return json.loads(response["HX-Trigger"])["toast"]["message"]


def names(gym):
    return [e.name for e in tracked_exercises(gym)]


# ---------------------------------------------------------------- tracked lifts in Settings


def test_new_gyms_track_the_three_default_lifts(gym):
    assert names(gym) == ["Snatch", "Clean & Jerk", "Back Squat"]
    install_pack(gym, "weightlifting")  # idempotent: never overwrites an existing list
    assert TrackedLift.objects.filter(gym=gym).count() == 3


def test_settings_shows_tracked_lifts(coach_client):
    html = coach_client.get("/coach/settings/").content.decode()
    assert 'id="trackedLifts"' in html and "3 of 6" in html
    assert "Stop tracking Clean &amp; Jerk" in html


def test_add_remove_and_reorder(coach_client, gym):
    response = coach_client.post("/coach/settings/lifts/add/", {"exercise": ex(gym, "fsq").pk}, **HX)
    assert "Now tracking Front Squat" in toast(response)
    assert names(gym)[-1] == "Front Squat"
    front = TrackedLift.objects.get(gym=gym, exercise__key="fsq")
    coach_client.post(f"/coach/settings/lifts/{front.pk}/move/up/", **HX)
    assert names(gym) == ["Snatch", "Clean & Jerk", "Front Squat", "Back Squat"]
    snatch = TrackedLift.objects.get(gym=gym, exercise__key="sn")
    assert "stay in each athlete's history" in toast(
        coach_client.post(f"/coach/settings/lifts/{snatch.pk}/remove/", **HX)
    )
    assert names(gym) == ["Clean & Jerk", "Front Squat", "Back Squat"]


@pytest.mark.parametrize("key,reason", [("sn", "already tracked"), ("bike", "timed"), ("mob", "timed")])
def test_only_untracked_rep_lifts_can_be_added(coach_client, gym, key, reason):
    response = coach_client.post("/coach/settings/lifts/add/", {"exercise": ex(gym, key).pk}, **HX)
    assert toast(response) == "Pick a lift to track", reason
    assert TrackedLift.objects.filter(gym=gym).count() == 3


def test_archived_and_other_gyms_exercises_cannot_be_tracked(coach_client, gym):
    archived = ex(gym, "fsq")
    archived.archived = True
    archived.save()
    other = Gym.objects.create(name="Elsewhere")
    install_pack(other, "weightlifting")
    for pk in [archived.pk, ex(other, "fsq").pk]:
        assert (
            toast(coach_client.post("/coach/settings/lifts/add/", {"exercise": pk}, **HX))
            == "Pick a lift to track"
        )


def test_cap_on_tracked_lifts(coach_client, gym):
    for key in ["fsq", "psq", "pp"]:
        coach_client.post("/coach/settings/lifts/add/", {"exercise": ex(gym, key).pk}, **HX)
    assert TrackedLift.objects.filter(gym=gym).count() == MAX_TRACKED_LIFTS
    response = coach_client.post("/coach/settings/lifts/add/", {"exercise": ex(gym, "sp").pk}, **HX)
    assert toast(response) == f"Track up to {MAX_TRACKED_LIFTS} lifts"


def test_other_gyms_tracked_lifts_are_404(coach_client, make_user):
    other = Gym.objects.create(name="Elsewhere")
    install_pack(other, "weightlifting")
    theirs = TrackedLift.objects.filter(gym=other).first()
    assert coach_client.post(f"/coach/settings/lifts/{theirs.pk}/remove/", **HX).status_code == 404
    assert coach_client.post(f"/coach/settings/lifts/{theirs.pk}/move/up/", **HX).status_code == 404


def test_athletes_cannot_change_tracked_lifts(athlete_client, gym):
    assert (
        athlete_client.post("/coach/settings/lifts/add/", {"exercise": ex(gym, "fsq").pk})["Location"]
        == "/app/"
    )


# ---------------------------------------------------------------- everything follows the gym's list


@pytest.fixture
def general_gym(gym):
    """A gym that stopped tracking the snatch and tracks the front squat instead."""
    TrackedLift.objects.filter(gym=gym, exercise__key="sn").delete()
    TrackedLift.objects.create(gym=gym, exercise=ex(gym, "fsq"), order=9)
    return gym


def test_onboarding_asks_for_the_gyms_lifts(athlete_client, general_gym):
    html = athlete_client.get("/app/welcome/").content.decode()
    assert "Front Squat 1RM (kg)" in html and "Snatch 1RM" not in html
    labels = [m.label for m in metric_specs(general_gym)]
    assert labels == [
        "Bodyweight",
        "Height",
        "Clean & Jerk 1RM",
        "Back Squat 1RM",
        "Front Squat 1RM",
        "Years training",
    ]


def test_metrics_tab_and_header_follow_the_list_and_keep_history(coach_client, athlete, general_gym):
    MaxEntry.objects.create(
        athlete=athlete, exercise=ex(general_gym, "sn"), date="2026-09-01", kg=80, source="coach"
    )
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/metrics/").content.decode()
    assert "Front Squat 1RM" in html and "Snatch 1RM" not in html
    assert '<span class="l">Front Squat</span>' in html  # header stat
    assert "Recent measurements" in html and ">Snatch<" in html  # untracked lift's history is kept
    untracked = lift_field(general_gym, "sn")
    assert (
        coach_client.get(f"/coach/athletes/{athlete.pk}/metrics/{untracked}/edit/", **HX).status_code == 404
    )


def test_save_metrics_ignores_lifts_the_gym_does_not_track(athlete, general_gym):
    other = Gym.objects.create(name="Elsewhere")
    install_pack(other, "weightlifting")
    save_metrics(
        athlete,
        {
            lift_field(general_gym, "sn"): Decimal("80"),
            lift_field(other, "sn"): Decimal("90"),
            lift_field(general_gym, "fsq"): Decimal("100"),
        },
        source="coach",
    )
    assert list(MaxEntry.objects.values_list("exercise__key", flat=True)) == ["fsq"]


def test_a_gym_tracking_no_lifts_still_onboards(athlete_client, athlete, gym):
    TrackedLift.objects.filter(gym=gym).delete()
    html = athlete_client.get("/app/welcome/").content.decode()
    assert "1RM" not in html and "Bodyweight" in html
    athlete_client.post("/app/welcome/", {"bodyweight": "70"})
    assert "2 fields left blank" in athlete_client.get("/app/welcome/done/").content.decode()


def test_reminder_lists_the_gyms_lift_names(coach_client, athlete, general_gym):
    from django.core import mail

    coach_client.post(f"/coach/athletes/{athlete.pk}/remind/", **HX)
    assert "Front Squat 1RM" in mail.outbox[0].body and "Snatch" not in mail.outbox[0].body


# ---------------------------------------------------------------- archive untracks; delete for good


def test_archiving_a_tracked_lift_untracks_it(coach_client, gym):
    listing = coach_client.get("/coach/programming/exercises/").content.decode()
    assert listing.count("also a tracked lift") == 3  # the archive confirmation warns for tracked lifts only
    response = coach_client.post(f"/coach/programming/exercises/{ex(gym, 'sn').pk}/archive/", **HX)
    assert "removed from tracked lifts" in toast(response)
    assert names(gym) == ["Clean & Jerk", "Back Squat"]
    coach_client.post(f"/coach/programming/exercises/{ex(gym, 'sn').pk}/restore/", **HX)
    assert names(gym) == ["Clean & Jerk", "Back Squat"]  # restoring doesn't re-track


def archive(gym, key):
    e = ex(gym, key)
    e.archived = True
    e.save()
    return e


def test_only_archived_exercises_can_be_deleted(coach_client, gym):
    active = ex(gym, "rdl")
    html = coach_client.get(f"/coach/programming/exercises/{active.pk}/delete/", **HX).content.decode()
    assert "Archive the exercise before deleting it." in html and "Delete permanently" not in html
    assert toast(coach_client.post(f"/coach/programming/exercises/{active.pk}/delete/", **HX)) == (
        "Archive the exercise before deleting it."
    )
    assert Exercise.objects.filter(pk=active.pk).exists()


def test_delete_warning_spells_out_the_impact(coach_client, gym, athlete):
    snatch = archive(gym, "sn")
    MaxEntry.objects.create(athlete=athlete, exercise=snatch, date="2026-09-01", kg=80, source="coach")
    MaxEntry.objects.create(athlete=athlete, exercise=snatch, date="2026-09-08", kg=82, source="coach")
    html = coach_client.get(f"/coach/programming/exercises/{snatch.pk}/delete/", **HX).content.decode()
    assert "2 max entries from the history of Maya Torres" in html
    assert (
        "Hang Snatch (knee), Power Snatch, Snatch Balance, Snatch Pull, Tempo Snatch DL (5s up) take" in html
    )


def test_delete_removes_history_and_resets_dependents(coach_client, gym, athlete):
    snatch = archive(gym, "sn")  # no special case: even the snatch can go
    MaxEntry.objects.create(athlete=athlete, exercise=snatch, date="2026-09-01", kg=80, source="coach")
    response = coach_client.post(f"/coach/programming/exercises/{snatch.pk}/delete/", **HX)
    assert toast(response) == "“Snatch” deleted along with 1 max entry"
    assert json.loads(response["HX-Trigger"])["exercisesChanged"] is True
    assert not Exercise.objects.filter(pk=snatch.pk).exists()
    assert not MaxEntry.objects.filter(athlete=athlete).exists()
    assert ex(gym, "psn").percent_of is None


def test_delete_other_gyms_exercise_is_404(coach_client, make_user):
    other = Gym.objects.create(name="Elsewhere")
    install_pack(other, "weightlifting")
    Coach.objects.create(user=make_user("o@example.com"), gym=other)
    theirs = archive(other, "rdl")
    assert coach_client.post(f"/coach/programming/exercises/{theirs.pk}/delete/", **HX).status_code == 404


def test_deletion_handles_every_model_that_points_at_an_exercise():
    """Guard for later phases: a new ForeignKey to Exercise must be counted in
    deletion_impact() and cleared in delete_exercise() (apps/exercises/deletion.py),
    then added here."""
    handled = {
        ("accounts", "maxentry", "exercise"),
        ("exercises", "exercise", "percent_of"),
        ("exercises", "trackedlift", "exercise"),
        ("exercises", "exercise_tags", "exercise"),  # tag links go with the exercise automatically
        ("programs", "prescription", "exercise"),
        ("workouts", "sessionexercise", "exercise"),  # link cleared; the name and sets stay
        ("library", "templateslot", "exercise"),  # fixed slots removed; tag slots re-defaulted
    }
    pointing = {
        (f.related_model._meta.app_label, f.related_model._meta.model_name, f.field.name)
        for f in Exercise._meta.get_fields(include_hidden=True)  # hidden: related_name="+" links too
        if f.auto_created and not f.concrete and (f.one_to_many or f.one_to_one)
    }
    assert pointing == handled, f"Update apps/exercises/deletion.py for: {pointing - handled}"
