import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from apps.accounts.models import Athlete, Coach, Gym
from apps.exercises.models import Exercise

from ..conftest import PASSWORD

pytestmark = pytest.mark.django_db
User = get_user_model()


def login(client, email, password=PASSWORD):
    return client.post("/accounts/login/", {"username": email, "password": password})


def test_login_page_renders_the_mockup_card(client):
    html = client.get("/accounts/login/").content.decode()
    assert 'class="login-card"' in html and "Create a gym" in html


def test_coach_lands_on_coach_app_and_email_is_case_insensitive(client, coach):
    response = login(client, "DANA@Example.com")
    assert response.status_code == 302
    assert client.get(response["Location"])["Location"] == "/coach/"


def test_athlete_lands_on_athlete_app(client, athlete):
    login(client, "maya@example.com")
    assert client.get("/")["Location"] == "/app/"


def test_user_with_both_profiles_lands_on_coach_app(client, coach):
    Athlete.objects.create(user=coach.user, coach=coach, gym=coach.gym)
    login(client, "dana@example.com")
    assert client.get("/")["Location"] == "/coach/"
    html = client.get("/coach/").content.decode()
    assert "My training" in html  # switcher to the athlete app


def test_user_with_no_profile_sees_no_profile_page(client, make_user):
    make_user("lost@example.com")
    login(client, "lost@example.com")
    assert client.get("/")["Location"] == "/accounts/no-profile/"
    assert "isn't linked to a gym" in client.get("/accounts/no-profile/").content.decode()


def test_wrong_password_shows_an_error(client, coach):
    response = login(client, "dana@example.com", "nope")
    assert response.status_code == 200
    assert "form-errors" in response.content.decode()


@pytest.mark.parametrize(
    "url", ["/coach/", "/coach/settings/", "/coach/invites/new/", "/app/", "/app/welcome/"]
)
def test_anonymous_users_are_sent_to_login(client, url):
    response = client.get(url)
    assert response.status_code == 302 and response["Location"].startswith("/accounts/login/?next=")


def test_athletes_cannot_open_coach_pages(athlete_client):
    assert athlete_client.get("/coach/settings/")["Location"] == "/app/"


def test_coaches_without_an_athlete_profile_bounce_off_the_athlete_app(coach_client):
    assert coach_client.get("/app/")["Location"] == "/coach/"


def test_logout_is_a_post(coach_client):
    response = coach_client.post("/accounts/logout/")
    assert response.status_code == 302
    assert coach_client.get("/coach/").status_code == 302


def test_signup_creates_gym_coach_and_starter_library(client):
    response = client.post(
        "/accounts/signup/",
        {
            "name": "Sam Coach",
            "email": "Sam@Example.com",
            "password": PASSWORD,
            "gym_name": "Barbell Club",
            "units": "lb",
            "browser_timezone": "Europe/London",
        },
    )
    assert response.status_code == 302 and response["Location"] == "/coach/"
    user = User.objects.get(email="Sam@example.com")
    coach = Coach.objects.get(user=user)
    assert coach.gym.name == "Barbell Club" and coach.gym.units == "lb"
    assert coach.gym.timezone == user.timezone == "Europe/London"
    assert Exercise.objects.filter(gym=coach.gym).count() == 24
    assert client.get("/coach/").status_code == 200  # signed in


def test_signup_rejects_bad_timezone_duplicates_and_weak_passwords(client, coach):
    response = client.post(
        "/accounts/signup/",
        {
            "name": "X",
            "email": "dana@example.com",
            "password": "123",
            "gym_name": "G",
            "units": "kg",
            "browser_timezone": "Mars/Base",
        },
    )
    html = response.content.decode()
    assert response.status_code == 200
    assert "already exists" in html and "too short" in html
    assert Gym.objects.count() == 1


def test_signup_falls_back_to_utc_for_unknown_browser_zone(client):
    client.post(
        "/accounts/signup/",
        {
            "name": "Z",
            "email": "z@example.com",
            "password": PASSWORD,
            "gym_name": "G",
            "units": "kg",
            "browser_timezone": "Not/AZone",
        },
    )
    assert User.objects.get(email="z@example.com").timezone == "UTC"


def test_password_reset_round_trip(client, coach):
    response = client.post("/accounts/password-reset/", {"email": "dana@example.com"})
    assert response["Location"] == "/accounts/password-reset/sent/"
    assert len(mail.outbox) == 1
    link = re.search(r"http://testserver(/accounts/password-reset/\S+/)", mail.outbox[0].body).group(1)
    form_url = client.get(link)["Location"]  # Django swaps the token into the session
    response = client.post(
        form_url, {"new_password1": "brand-new-pass-77", "new_password2": "brand-new-pass-77"}
    )
    assert response["Location"] == "/accounts/password-reset/done/"
    assert login(client, "dana@example.com", "brand-new-pass-77").status_code == 302


def test_password_reset_does_not_reveal_unknown_emails(client):
    response = client.post("/accounts/password-reset/", {"email": "nobody@example.com"})
    assert response["Location"] == "/accounts/password-reset/sent/"
    assert len(mail.outbox) == 0
