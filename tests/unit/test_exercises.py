import json

import pytest

from apps.accounts.models import Coach, Gym, MaxEntry
from apps.exercises.models import Exercise
from apps.exercises.starter import install_starter_library

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def results(client, **params):
    return client.get("/coach/programming/exercises/", params, HTTP_HX_TARGET="exlibResults", **HX)


def test_programming_opens_on_the_library(coach_client):
    response = coach_client.get("/coach/programming/")
    assert response["Location"] == "/coach/programming/exercises/"
    html = coach_client.get("/coach/programming/exercises/").content.decode()
    assert "24 exercises" in html and "Snatch Balance" in html and 'class="tabs"' in html


def test_search_matches_name_tag_or_cue(coach_client):
    html = results(coach_client, q="squat").content.decode()
    assert "Back Squat" in html and "Front Squat" in html and "Power Clean" not in html
    assert "<html" not in html  # partial only
    assert "Ab Wheel" in results(coach_client, q="no-equip").content.decode()  # tag text
    assert "Pendlay Row" in results(coach_client, q="dead stop").content.decode()  # cue


def test_tag_filters_combine_with_and(coach_client):
    html = results(coach_client, tag=["overhead", "strength"]).content.decode()
    assert "Push Press" in html and "Strict Press" in html
    assert "Overhead Squat" not in html  # overhead but not strength
    assert "2 exercises" in html


def test_create_exercise(coach_client, coach):
    response = coach_client.post(
        "/coach/programming/exercises/new/",
        {
            "name": "  Snatch   Pull + Snatch ",
            "category": "snatch",
            "measure": "reps",
            "percent_of": Exercise.objects.get(gym=coach.gym, key="sn").pk,
            "tags": ["technique", "speed"],
            "youtube_url": "youtube.com/watch?v=abc",
            "cue": "Stay over it",
        },
        **HX,
    )
    trigger = json.loads(response["HX-Trigger"])
    assert trigger["exercisesChanged"] is True and "added to the library" in trigger["toast"]["message"]
    assert response.content == b""  # empties #modal, i.e. closes it
    ex = Exercise.objects.get(gym=coach.gym, name="Snatch Pull + Snatch")
    assert ex.tags == ["technique", "speed"] and ex.percent_of.key == "sn" and ex.key == ""
    assert ex.youtube_url == "https://youtube.com/watch?v=abc"


def test_duplicate_names_are_rejected_case_insensitively(coach_client):
    html = coach_client.post(
        "/coach/programming/exercises/new/",
        {"name": "back squat", "category": "squat", "measure": "reps"},
        **HX,
    ).content.decode()
    assert "already has an exercise with this name" in html


def test_percent_of_must_be_a_base_lift_and_not_itself(coach_client, coach):
    fsq = Exercise.objects.get(gym=coach.gym, key="fsq")
    bsq = Exercise.objects.get(gym=coach.gym, key="bsq")
    # Front squat is not a base lift (it points at back squat), so it isn't offered.
    html = coach_client.post(
        f"/coach/programming/exercises/{bsq.pk}/edit/",
        {"name": "Back Squat", "category": "squat", "measure": "reps", "percent_of": fsq.pk},
        **HX,
    ).content.decode()
    assert "errorlist" in html
    # Back squat can't start pointing elsewhere while others depend on it.
    sn = Exercise.objects.get(gym=coach.gym, key="sn")
    html = coach_client.post(
        f"/coach/programming/exercises/{bsq.pk}/edit/",
        {"name": "Back Squat", "category": "squat", "measure": "reps", "percent_of": sn.pk},
        **HX,
    ).content.decode()
    assert "must keep its own max" in html


def test_edit_keeps_the_starter_key(coach_client, coach):
    sn = Exercise.objects.get(gym=coach.gym, key="sn")
    coach_client.post(
        f"/coach/programming/exercises/{sn.pk}/edit/",
        {"name": "Full Snatch", "category": "snatch", "measure": "reps", "tags": ["speed"]},
        **HX,
    )
    sn.refresh_from_db()
    assert sn.name == "Full Snatch" and sn.key == "sn"


def test_archive_and_restore(coach_client, coach, athlete):
    sn = Exercise.objects.get(gym=coach.gym, key="sn")
    MaxEntry.objects.create(athlete=athlete, exercise=sn, date="2026-09-01", kg=80, source="coach")
    response = coach_client.post(f"/coach/programming/exercises/{sn.pk}/archive/", **HX)
    assert "still take percentages from it" in json.loads(response["HX-Trigger"])["toast"]["message"]
    sn.refresh_from_db()
    assert sn.archived and MaxEntry.objects.filter(exercise=sn).exists()  # history intact
    assert "Snatch Balance" in results(coach_client).content.decode()
    assert "<b>Snatch</b>" not in results(coach_client).content.decode()
    assert "Restore" in results(coach_client, archived="1").content.decode()
    coach_client.post(f"/coach/programming/exercises/{sn.pk}/restore/", **HX)
    sn.refresh_from_db()
    assert not sn.archived


def test_other_gyms_exercises_are_invisible(coach_client, make_user):
    other = Gym.objects.create(name="Elsewhere")
    install_starter_library(other)
    Coach.objects.create(user=make_user("x@example.com"), gym=other)
    theirs = Exercise.objects.get(gym=other, key="sn")
    assert coach_client.get(f"/coach/programming/exercises/{theirs.pk}/edit/", **HX).status_code == 404
    assert coach_client.post(f"/coach/programming/exercises/{theirs.pk}/archive/", **HX).status_code == 404
    assert "24 exercises" in results(coach_client).content.decode()


def test_athletes_cannot_use_the_library(athlete_client):
    assert athlete_client.get("/coach/programming/exercises/")["Location"] == "/app/"
