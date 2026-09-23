import json

import pytest

from apps.accounts.models import Athlete, Coach, Gym, Invite
from apps.workouts.models import CheckinQuestion, copy_defaults_to, install_default_questions

from ..conftest import PASSWORD

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def defaults(gym):
    install_default_questions(gym)
    return list(CheckinQuestion.objects.gym_defaults(gym).active())


@pytest.fixture
def maya(athlete, defaults):
    copy_defaults_to(athlete)
    return athlete


def toast(response):
    return json.loads(response["HX-Trigger"])["toast"]["message"]


def test_new_gyms_get_the_mockup_defaults(client):
    client.post(
        "/accounts/signup/",
        {
            "name": "S",
            "email": "s@example.com",
            "password": PASSWORD,
            "gym_name": "G",
            "units": "kg",
            "browser_timezone": "UTC",
        },
    )
    texts = list(CheckinQuestion.objects.filter(gym__name="G").values_list("text", flat=True))
    assert texts == ["How recovered do you feel today?", "Anything affecting today's session?"]


def test_joining_athletes_get_their_own_copy(client, coach, defaults):
    invite = Invite.objects.create(coach=coach)
    client.post(f"/join/{invite.token}/", {"name": "N", "email": "n@example.com", "password": PASSWORD})
    athlete = Athlete.objects.get(user__email="n@example.com")
    copies = list(CheckinQuestion.objects.for_athlete(athlete).active())
    assert [q.text for q in copies] == [q.text for q in defaults]
    assert all(q.gym_id is None for q in copies)


def test_defaults_page(coach_client, defaults):
    html = coach_client.get("/coach/programming/questions/").content.decode()
    assert "How recovered do you feel today?" in html and "Poor sleep" in html
    assert 'id="defQBuilder"' in html


def test_add_edit_move_and_archive_defaults(coach_client, gym, defaults):
    base = "/coach/programming/questions/"
    response = coach_client.post(f"{base}add/scale/", **HX)
    assert "Question added" in toast(response)
    new = CheckinQuestion.objects.gym_defaults(gym).active().last()
    response = coach_client.post(
        f"{base}{new.pk}/update/",
        {"text": "  How was   sleep? ", "low_label": "awful", "high_label": "great"},
        **HX,
    )
    assert "push them to update existing athletes" in toast(response)
    new.refresh_from_db()
    assert (new.text, new.low_label, new.high_label) == ("How was sleep?", "awful", "great")
    coach_client.post(f"{base}{new.pk}/move/up/", **HX)
    order = list(CheckinQuestion.objects.gym_defaults(gym).active().values_list("pk", flat=True))
    assert order[1] == new.pk
    coach_client.post(f"{base}{new.pk}/archive/", **HX)
    new.refresh_from_db()
    assert new.archived and new.pk not in CheckinQuestion.objects.gym_defaults(gym).active().values_list(
        "pk", flat=True
    )


def test_blank_wording_is_refused(coach_client, defaults):
    q = defaults[0]
    response = coach_client.post(f"/coach/programming/questions/{q.pk}/update/", {"text": "   "}, **HX)
    assert "needs some wording" in toast(response)
    q.refresh_from_db()
    assert q.text == "How recovered do you feel today?"


def test_options(coach_client, defaults):
    mc = defaults[1]
    base = f"/coach/programming/questions/{mc.pk}/options/"
    coach_client.post(f"{base}add/", {"option": "Travelling"}, **HX)
    mc.refresh_from_db()
    assert mc.options[-1] == "Travelling"
    assert "already there" in toast(coach_client.post(f"{base}add/", {"option": "Travelling"}, **HX))
    coach_client.post(f"{base}0/remove/", **HX)
    mc.refresh_from_db()
    assert mc.options[0] == "Legs are sore"
    while len(mc.options) > 2:
        coach_client.post(f"{base}0/remove/", **HX)
        mc.refresh_from_db()
    assert "at least two options" in toast(coach_client.post(f"{base}0/remove/", **HX))
    assert coach_client.post(f"{base}9/remove/", **HX).status_code == 404


def test_athlete_copy_is_independent_of_defaults(coach_client, maya, defaults):
    theirs = CheckinQuestion.objects.for_athlete(maya).active().first()
    response = coach_client.post(
        f"/coach/athletes/{maya.pk}/questions/{theirs.pk}/update/",
        {"text": "Energy today?", "low_label": "", "high_label": ""},
        **HX,
    )
    assert toast(response) == "Updated — live from Maya's next session"
    defaults[0].refresh_from_db()
    assert defaults[0].text == "How recovered do you feel today?"
    # A default question id can't be edited through the athlete URL, and vice versa.
    assert (
        coach_client.post(f"/coach/athletes/{maya.pk}/questions/{defaults[0].pk}/archive/", **HX).status_code
        == 404
    )
    assert coach_client.post(f"/coach/programming/questions/{theirs.pk}/archive/", **HX).status_code == 404


def test_reset_archives_the_athletes_old_questions(coach_client, maya):
    old = CheckinQuestion.objects.for_athlete(maya).active().first()
    coach_client.post(f"/coach/athletes/{maya.pk}/questions/{old.pk}/update/", {"text": "Changed"}, **HX)
    coach_client.post(f"/coach/athletes/{maya.pk}/questions/reset/", **HX)
    old.refresh_from_db()
    assert old.archived and old.text == "Changed"  # kept for past answers
    assert (
        CheckinQuestion.objects.for_athlete(maya).active().first().text == "How recovered do you feel today?"
    )


def test_push_defaults_reaches_only_your_athletes(coach_client, coach, maya, make_user):
    other = Coach.objects.create(user=make_user("c2@example.com"), gym=coach.gym)
    theirs = Athlete.objects.create(user=make_user("t@example.com"), coach=other, gym=coach.gym)
    copy_defaults_to(theirs)
    coach_client.post("/coach/programming/questions/add/choice/", **HX)
    response = coach_client.post("/coach/programming/questions/push/", **HX)
    assert toast(response) == "Default questions pushed to your 1 athlete"
    assert CheckinQuestion.objects.for_athlete(maya).active().count() == 3
    assert CheckinQuestion.objects.for_athlete(theirs).active().count() == 2


def test_other_gyms_defaults_are_untouchable(coach_client, make_user):
    other = Gym.objects.create(name="Elsewhere")
    install_default_questions(other)
    q = CheckinQuestion.objects.gym_defaults(other).first()
    assert coach_client.post(f"/coach/programming/questions/{q.pk}/archive/", **HX).status_code == 404


def test_unknown_question_type_is_404(coach_client, defaults):
    assert coach_client.post("/coach/programming/questions/add/essay/", **HX).status_code == 404


def test_a_question_needs_exactly_one_owner(gym, maya):
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        CheckinQuestion.objects.create(gym=gym, athlete=maya, type="scale", text="x")
