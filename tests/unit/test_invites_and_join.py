import datetime
import json
import re
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import Athlete, Coach, Gym, Invite, InviteStatus, User

from ..conftest import PASSWORD, lift_field

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def test_invite_modal_renders(coach_client):
    html = coach_client.get("/coach/invites/new/", **HX).content.decode()
    assert 'class="modal open"' in html and 'hx-post="/coach/invites/"' in html


def test_invite_by_email_sends_a_join_link(coach_client, coach):
    response = coach_client.post("/coach/invites/", {"email": "new@example.com"}, **HX)
    invite = Invite.objects.get()
    assert invite.coach == coach and invite.email == "new@example.com"
    assert json.loads(response["HX-Trigger"])["toast"]["message"] == "Invite sent to new@example.com"
    assert f"/join/{invite.token}/" in response.content.decode()
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["new@example.com"]
    assert "Dana Whitfield invited you to train with Iron Ridge" in mail.outbox[0].subject
    assert f"http://testserver/join/{invite.token}/" in mail.outbox[0].body


def test_invite_without_email_just_makes_a_link(coach_client):
    response = coach_client.post("/coach/invites/", {"email": ""}, **HX)
    assert Invite.objects.get().email == ""
    assert len(mail.outbox) == 0
    assert "Share this link" in response.content.decode()


def test_invalid_invite_email_rerenders_the_form(coach_client):
    html = coach_client.post("/coach/invites/", {"email": "not-an-email"}, **HX).content.decode()
    assert "errorlist" in html and Invite.objects.count() == 0


def test_pending_list_hides_used_expired_and_revoked(coach_client, coach):
    Invite.objects.create(coach=coach, email="live@example.com")
    Invite.objects.create(coach=coach, email="used@example.com", status=InviteStatus.ACCEPTED)
    Invite.objects.create(coach=coach, email="gone@example.com", status=InviteStatus.REVOKED)
    Invite.objects.create(
        coach=coach, email="old@example.com", expires_at=timezone.now() - datetime.timedelta(days=1)
    )
    html = coach_client.get("/coach/invites/pending/", **HX).content.decode()
    assert "live@example.com" in html
    assert not any(e in html for e in ["used@", "gone@", "old@"])


def test_revoke_only_your_own_invites(coach_client, coach, make_user):
    mine = Invite.objects.create(coach=coach)
    other_coach = Coach.objects.create(user=make_user("other@example.com"), gym=Gym.objects.create(name="O"))
    theirs = Invite.objects.create(coach=other_coach)
    assert coach_client.post(f"/coach/invites/{theirs.pk}/revoke/", **HX).status_code == 404
    coach_client.post(f"/coach/invites/{mine.pk}/revoke/", **HX)
    mine.refresh_from_db()
    assert mine.status == InviteStatus.REVOKED


def test_join_page_shows_who_invited(client, coach):
    invite = Invite.objects.create(coach=coach, email="maya@new.example")
    html = client.get(f"/join/{invite.token}/").content.decode()
    assert "Dana Whitfield — Iron Ridge Weightlifting" in html
    assert 'value="maya@new.example"' in html


@pytest.mark.parametrize("state", ["unknown", "expired", "revoked", "accepted"])
def test_unusable_invites_are_refused(client, coach, state):
    token = "does-not-exist"
    if state != "unknown":
        invite = Invite.objects.create(coach=coach)
        token = invite.token
        if state == "expired":
            invite.expires_at = timezone.now() - datetime.timedelta(minutes=1)
        else:
            invite.status = state
        invite.save()
    response = client.get(f"/join/{token}/")
    assert response.status_code == 410 and "can't be used" in response.content.decode()


def join(client, invite, **overrides):
    data = {
        "name": "Nia Park",
        "email": "nia@example.com",
        "password": PASSWORD,
        "browser_timezone": "America/Chicago",
        **overrides,
    }
    return client.post(f"/join/{invite.token}/", data)


def test_joining_creates_an_athlete_and_signs_them_in(client, coach):
    invite = Invite.objects.create(coach=coach)
    response = join(client, invite)
    assert response["Location"] == "/app/welcome/"
    user = User.objects.get(email="nia@example.com")
    athlete = Athlete.objects.get(user=user)
    assert athlete.coach == coach and athlete.gym == coach.gym and athlete.units == coach.gym.units
    assert user.timezone == "America/Chicago"
    invite.refresh_from_db()
    assert invite.status == InviteStatus.ACCEPTED and invite.accepted_by == user
    assert client.get("/app/welcome/").status_code == 200
    # The link is now spent.
    client.post("/accounts/logout/")
    assert client.get(f"/join/{invite.token}/").status_code == 410


def test_joining_defaults_to_the_gym_time_zone(client, coach):
    invite = Invite.objects.create(coach=coach)
    join(client, invite, browser_timezone="")
    assert User.objects.get(email="nia@example.com").timezone == "America/New_York"


def test_joining_with_an_existing_email_asks_to_log_in(client, coach, athlete):
    invite = Invite.objects.create(coach=coach)
    html = join(client, invite, email="maya@example.com").content.decode()
    assert "already exists" in html
    invite.refresh_from_db()
    assert invite.status == InviteStatus.PENDING


def test_a_signed_in_coach_can_accept_an_invite_to_train(client, coach, make_user):
    head = Coach.objects.create(user=make_user("head@example.com", "Head"), gym=coach.gym)
    invite = Invite.objects.create(coach=head)
    client.force_login(coach.user)
    assert "Join as Dana Whitfield" in client.get(f"/join/{invite.token}/").content.decode()
    assert client.post(f"/join/{invite.token}/")["Location"] == "/app/welcome/"
    coach.user.refresh_from_db()
    assert coach.user.athlete_profile.coach == head


def test_metrics_are_saved_as_history_in_kg(athlete_client, athlete):
    gym = athlete.gym
    response = athlete_client.post(
        "/app/welcome/",
        {
            "bodyweight": "63.8",
            "height_cm": "168",
            lift_field(gym, "sn"): "82",
            lift_field(gym, "cj"): "104",
            lift_field(gym, "bsq"): "",
            "years_training": "3-5",
        },
    )
    assert response["Location"] == "/app/welcome/done/"
    athlete.refresh_from_db()
    assert athlete.height_cm == Decimal("168.0") and athlete.years_training == "3-5"
    assert athlete.current_bodyweight().kg == Decimal("63.80")
    assert {e.exercise.key: e.kg for e in athlete.current_maxes().values()} == {
        "sn": Decimal("82.00"),
        "cj": Decimal("104.00"),
    }
    assert all(e.source == "onboarding" for e in athlete.maxes.all())
    html = athlete_client.get("/app/welcome/done/").content.decode()
    assert "1 field left blank" in html


def test_metrics_in_pounds_are_converted(athlete_client, athlete):
    athlete.units = "lb"
    athlete.save()
    athlete_client.post("/app/welcome/", {"bodyweight": "141", lift_field(athlete.gym, "bsq"): "300"})
    assert athlete.current_bodyweight().kg == Decimal("63.96")
    assert next(iter(athlete.current_maxes().values())).kg == Decimal("136.08")


def test_skip_all(athlete_client, athlete):
    response = athlete_client.post(
        "/app/welcome/", {"skip_all": "1", lift_field(athlete.gym, "sn"): "999999"}
    )
    assert response["Location"] == "/app/welcome/done/"
    assert athlete.maxes.count() == 0
    assert "all metrics skipped" in athlete_client.get("/app/welcome/done/").content.decode()


def test_metrics_form_rejects_nonsense(athlete_client, athlete):
    html = athlete_client.post("/app/welcome/", {"bodyweight": "5"}).content.decode()
    assert "errorlist" in html and athlete.bodyweights.count() == 0


def test_invite_email_link_matches_the_route(coach_client):
    coach_client.post("/coach/invites/", {"email": "x@example.com"}, **HX)
    path = re.search(r"http://testserver(/join/\S+/)", mail.outbox[0].body).group(1)
    assert coach_client.get(path).status_code == 200
