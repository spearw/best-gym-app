"""Starter packs, per-gym categories and tags, and per-gym week types."""

import json

import pytest

from apps.accounts.models import Coach, Gym
from apps.exercises.models import Category, Exercise, Tag, tracked_exercises
from apps.exercises.starter import install_pack
from apps.programs import views as week_type_views
from apps.programs.models import WeekType
from apps.workouts.models import CheckinQuestion

from ..conftest import PASSWORD, cat, tag_ids

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def toast(response):
    return json.loads(response["HX-Trigger"])["toast"]["message"]


# ---------------------------------------------------------------- starter packs


def signup(client, starter, email="s@example.com"):
    return client.post(
        "/accounts/signup/",
        {
            "name": "Sam",
            "email": email,
            "password": PASSWORD,
            "gym_name": f"{starter} gym",
            "units": "kg",
            "starter": starter,
            "browser_timezone": "UTC",
        },
    )


def test_signup_offers_three_starters_and_requires_a_choice(client):
    html = client.get("/accounts/signup/").content.decode()
    assert "Olympic weightlifting" in html and "General strength" in html and "Start empty" in html
    response = client.post(
        "/accounts/signup/",
        {"name": "S", "email": "x@example.com", "password": PASSWORD, "gym_name": "G", "units": "kg"},
    )
    assert "Pick how you&#x27;d like to start." in response.content.decode()
    assert not Gym.objects.filter(name="G").exists()


def test_general_strength_pack(client):
    signup(client, "general")
    gym = Gym.objects.get(name="general gym")
    assert [c.name for c in gym.categories.all()] == [
        "Squat",
        "Hinge",
        "Push",
        "Pull",
        "Single-leg",
        "Core",
        "Carry",
        "Conditioning",
        "Mobility",
    ]
    assert [w.name for w in gym.week_types.all()] == ["Hypertrophy", "Strength", "Power", "Deload", "Testing"]
    assert [e.name for e in tracked_exercises(gym)] == ["Back Squat", "Bench Press", "Deadlift"]
    rdl = Exercise.objects.get(gym=gym, name="Romanian Deadlift")
    assert rdl.percent_of.name == "Deadlift" and rdl.category.name == "Hinge"
    assert Exercise.objects.get(gym=gym, name="Farmer Carry").measure == "distance"
    assert not Exercise.objects.filter(gym=gym).exclude(youtube_url="").exists()  # no fake demo links
    assert CheckinQuestion.objects.gym_defaults(gym).count() == 2


def test_weightlifting_pack(client):
    signup(client, "weightlifting")
    gym = Gym.objects.get(name="weightlifting gym")
    assert Exercise.objects.filter(gym=gym).count() == 24
    assert [e.name for e in tracked_exercises(gym)] == ["Snatch", "Clean & Jerk", "Back Squat"]
    assert gym.week_types.count() == 6 and gym.tags.count() == 13


def test_empty_pack_has_basic_setup_only(client):
    signup(client, "empty")
    gym = Gym.objects.get(name="empty gym")
    assert not Exercise.objects.filter(gym=gym).exists() and not tracked_exercises(gym)
    assert [c.name for c in gym.categories.all()] == ["Strength", "Accessory", "Conditioning", "Mobility"]
    assert [w.name for w in gym.week_types.all()] == ["Build", "Push", "Deload"]
    assert not gym.tags.exists()
    # They can start adding exercises straight away.
    coach = Coach.objects.get(gym=gym)
    client.force_login(coach.user)
    client.post(
        "/coach/programming/exercises/new/",
        {"name": "Sled push", "category": cat(gym, "Conditioning").pk, "measure": "distance"},
        **HX,
    )
    assert Exercise.objects.filter(gym=gym, name="Sled push").exists()


def test_packs_install_on_top_of_each_other_without_duplicates(gym):
    install_pack(gym, "general")  # the fixture gym already has weightlifting
    names = [c.name.lower() for c in gym.categories.all()]
    assert len(names) == len(set(names))  # "Squat", "Pull"... not duplicated
    assert Exercise.objects.filter(gym=gym, name="Back Squat").count() == 1  # same name: kept, not duplicated
    assert Exercise.objects.filter(gym=gym, name="Bench Press").exists()  # new ones added
    assert [e.name for e in tracked_exercises(gym)] == ["Snatch", "Clean & Jerk", "Back Squat"]  # list kept


# ---------------------------------------------------------------- categories


BASE = "/coach/programming/"


def test_organise_page_lists_categories_and_tags_with_counts(coach_client):
    html = coach_client.get(f"{BASE}exercises/organise/").content.decode()
    assert 'id="categoriesCard"' in html and 'id="tagsCard"' in html
    assert "5 exercises" in html  # Snatch category: sn, psn, hsn, snb... per the pack


def test_add_rename_and_reorder_categories(coach_client, gym):
    response = coach_client.post(f"{BASE}categories/add/", {"name": "  Hinge  "}, **HX)
    assert "Category “Hinge” added" == toast(response)
    hinge = cat(gym, "Hinge")
    assert list(gym.categories.values_list("name", flat=True))[-1] == "Hinge"
    assert (
        toast(coach_client.post(f"{BASE}categories/add/", {"name": "squat"}, **HX))
        == "You already have a category called “squat”."
    )
    coach_client.post(f"{BASE}categories/{hinge.pk}/rename/", {f"name_{hinge.pk}": "Hinges"}, **HX)
    hinge.refresh_from_db()
    assert hinge.name == "Hinges"
    coach_client.post(f"{BASE}categories/{hinge.pk}/move/up/", **HX)
    assert list(gym.categories.values_list("name", flat=True))[-2] == "Hinges"


def test_renaming_a_category_to_blank_is_refused_and_redrawn(coach_client, gym):
    squat = cat(gym, "Squat")
    response = coach_client.post(f"{BASE}categories/{squat.pk}/rename/", {f"name_{squat.pk}": "  "}, **HX)
    assert response["HX-Retarget"] == "#categoriesCard" and toast(response) == "Give the category a name."
    squat.refresh_from_db()
    assert squat.name == "Squat"


def test_deleting_a_category_moves_its_exercises(coach_client, gym):
    press = cat(gym, "Press")
    ids = list(press.exercises.values_list("pk", flat=True))
    html = coach_client.get(f"{BASE}categories/{press.pk}/delete/", **HX).content.decode()
    assert "2 exercises are in this category" in html and "Move exercises to" in html
    html = coach_client.post(f"{BASE}categories/{press.pk}/delete/", {}, **HX).content.decode()
    assert "Pick where its exercises should go." in html  # nothing moved, nothing deleted
    accessory = cat(gym, "Accessory")
    response = coach_client.post(f"{BASE}categories/{press.pk}/delete/", {"move_to": accessory.pk}, **HX)
    assert toast(response) == "Moved 2 exercises to Accessory and deleted Press"
    assert json.loads(response["HX-Trigger-After-Swap"]) == {"closeModal": True}
    assert not Category.objects.filter(pk=press.pk).exists()
    assert set(Exercise.objects.filter(pk__in=ids).values_list("category__name", flat=True)) == {"Accessory"}


def test_archived_exercises_move_too(coach_client, gym):
    press = cat(gym, "Press")
    Exercise.objects.filter(category=press).update(archived=True)
    coach_client.post(f"{BASE}categories/{press.pk}/delete/", {"move_to": cat(gym, "Pull").pk}, **HX)
    assert Exercise.objects.filter(category__name="Pull", archived=True).count() == 2


def test_the_only_category_with_exercises_cannot_be_deleted(coach_client, gym):
    keep = cat(gym, "Snatch")
    Exercise.objects.filter(gym=gym).update(category=keep)
    Category.objects.filter(gym=gym).exclude(pk=keep.pk).delete()
    html = coach_client.get(f"{BASE}categories/{keep.pk}/delete/", **HX).content.decode()
    assert "Add another category first" in html
    coach_client.post(f"{BASE}categories/{keep.pk}/delete/", {}, **HX)
    assert Category.objects.filter(pk=keep.pk).exists()


def test_empty_category_deletes_directly(coach_client, gym):
    lonely = Category.objects.create(gym=gym, name="Lonely", order=99)
    response = coach_client.post(f"{BASE}categories/{lonely.pk}/delete/", {}, **HX)
    assert toast(response) == "Deleted Lonely"


def test_other_gyms_categories_and_tags_are_404(coach_client):
    other = Gym.objects.create(name="Elsewhere")
    install_pack(other, "weightlifting")
    c, t = cat(other, "Squat"), Tag.objects.filter(gym=other).first()
    for url in [
        f"{BASE}categories/{c.pk}/rename/",
        f"{BASE}categories/{c.pk}/delete/",
        f"{BASE}tags/{t.pk}/rename/",
        f"{BASE}tags/{t.pk}/delete/",
    ]:
        assert coach_client.post(url, {f"name_{c.pk}": "x", f"name_{t.pk}": "x"}, **HX).status_code == 404, (
            url
        )


# ---------------------------------------------------------------- tags


def test_tags_add_rename_limit_and_delete(coach_client, gym):
    assert (
        toast(coach_client.post(f"{BASE}tags/add/", {"name": "upper-body"}, **HX)) == "Tag “upper-body” added"
    )
    assert (
        toast(coach_client.post(f"{BASE}tags/add/", {"name": "x" * 25}, **HX))
        == "Keep tag names to 24 characters."
    )
    assert (
        toast(coach_client.post(f"{BASE}tags/add/", {"name": "STRENGTH"}, **HX))
        == "You already have a tag called “STRENGTH”."
    )
    speed = Tag.objects.get(gym=gym, name="speed")
    n = speed.exercises.count()
    coach_client.post(f"{BASE}tags/{speed.pk}/rename/", {f"name_{speed.pk}": "fast"}, **HX)
    speed.refresh_from_db()
    assert speed.name == "fast" and speed.exercises.count() == n  # exercises keep it under the new name
    response = coach_client.post(f"{BASE}tags/{speed.pk}/delete/", **HX)
    assert toast(response) == f"Deleted “fast” and removed it from {n} exercises"
    assert Exercise.objects.filter(gym=gym).count() == 24  # exercises themselves stay


def test_tag_filter_uses_the_gyms_tags(coach_client, gym):
    Tag.objects.create(gym=gym, name="mine")
    html = coach_client.get(f"{BASE}exercises/").content.decode()
    assert ">mine</label>" in html


# ---------------------------------------------------------------- week types


WT = "/coach/settings/week-types/"


def test_add_update_and_reorder_week_types(coach_client, gym):
    response = coach_client.post(f"{WT}add/", {"name": "Peaking", "colour": "#aa0000"}, **HX)
    assert toast(response) == "Week type “Peaking” added"
    peaking = WeekType.objects.get(gym=gym, name="Peaking")
    assert peaking.colour == "#AA0000"
    response = coach_client.post(
        f"{WT}{peaking.pk}/update/",
        {
            f"name_{peaking.pk}": "Peak",
            f"description_{peaking.pk}": "Openers",
            f"colour_{peaking.pk}": "#00aa00",
        },
        **HX,
    )
    assert f'id="wtPill-{peaking.pk}" style="--wkc:#00AA00' in response.content.decode()  # live pill preview
    peaking.refresh_from_db()
    assert (peaking.name, peaking.description, peaking.colour) == ("Peak", "Openers", "#00AA00")
    coach_client.post(f"{WT}{peaking.pk}/move/up/", **HX)
    assert list(gym.week_types.active().values_list("name", flat=True))[-2] == "Peak"


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("name", "", "Give the week type a name."),
        ("name", "deload", "You already have a week type called “deload”."),
        ("colour", "red", "Pick a colour like #2E9E5B"),
        ("description", "x" * 121, "Keep descriptions to 120 characters."),
    ],
)
def test_week_type_validation(coach_client, gym, field, value, message):
    wt = gym.week_types.get(name="Accumulation")
    data = {
        f"name_{wt.pk}": wt.name,
        f"colour_{wt.pk}": wt.colour,
        f"description_{wt.pk}": wt.description,
        f"{field}_{wt.pk}": value,
    }
    response = coach_client.post(f"{WT}{wt.pk}/update/", data, **HX)
    assert toast(response) == message and response["HX-Retarget"] == "#weekTypes"
    wt.refresh_from_db()
    assert wt.name == "Accumulation" and wt.colour == "#2E9E5B"


def test_unused_week_type_is_deleted(coach_client, gym):
    wt = gym.week_types.get(name="Cutting")
    assert toast(coach_client.post(f"{WT}{wt.pk}/remove/", **HX)) == "Deleted “Cutting”"
    assert not WeekType.objects.filter(pk=wt.pk).exists()


def test_week_type_in_use_is_archived_not_deleted(coach_client, gym, monkeypatch):
    # Nothing points at week types until phase 3; simulate a program week using it.
    monkeypatch.setattr(week_type_views, "usage_count", lambda wt: 3 if wt.name == "Cutting" else 0)
    wt = gym.week_types.get(name="Cutting")
    assert "used by 3 weeks, so it was archived" in toast(coach_client.post(f"{WT}{wt.pk}/remove/", **HX))
    wt.refresh_from_db()
    assert wt.archived and "Cutting" not in gym.week_types.active().values_list("name", flat=True)
    coach_client.post(f"{WT}{wt.pk}/restore/", **HX)
    wt.refresh_from_db()
    assert not wt.archived


def test_usage_count_sees_every_model_pointing_at_week_types(gym):
    """Guard for phase 3: usage_count() discovers users of WeekType itself, so new
    foreign keys (program weeks, template weeks, session logs) are counted without code changes."""
    assert week_type_views.usage_count(gym.week_types.first()) == 0


def test_other_gyms_week_types_are_404(coach_client):
    other = Gym.objects.create(name="Elsewhere")
    install_pack(other, "empty")
    wt = other.week_types.first()
    assert coach_client.post(f"{WT}{wt.pk}/remove/", **HX).status_code == 404


# ---------------------------------------------------------------- edit-then-click never loses the edit


def test_a_click_saves_wording_still_on_screen(coach_client, gym):
    """If a structural click (move, delete) reaches the server before the edit's own save,
    it still carries what's on screen and saves it first."""
    from apps.workouts.models import copy_defaults_to, install_default_questions  # noqa: F401

    install_default_questions(gym)
    q1, q2 = CheckinQuestion.objects.gym_defaults(gym).active()
    coach_client.post(
        f"{BASE}questions/{q1.pk}/move/down/",
        {f"text_{q1.pk}": "Edited while moving", f"text_{q2.pk}": q2.text},
        **HX,
    )
    q1.refresh_from_db()
    assert q1.text == "Edited while moving" and q1.order == 1

    squat = cat(gym, "Squat")
    coach_client.post(f"{BASE}categories/{squat.pk}/move/up/", {f"name_{squat.pk}": "Squats"}, **HX)
    squat.refresh_from_db()
    assert squat.name == "Squats"

    wt = gym.week_types.get(name="Deload")
    coach_client.post(
        f"{WT}{wt.pk}/move/up/",
        {f"name_{wt.pk}": "Recovery", f"colour_{wt.pk}": "#123456", f"description_{wt.pk}": "Easy"},
        **HX,
    )
    wt.refresh_from_db()
    assert (wt.name, wt.colour, wt.description) == ("Recovery", "#123456", "Easy")


def test_tag_ids_helper(gym):
    assert len(tag_ids(gym, "speed", "strength")) == 2
