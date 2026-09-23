import pytest

from apps.accounts.models import Gym

pytestmark = pytest.mark.django_db


def form(**overrides):
    return {
        "gym_name": "Iron Ridge WL",
        "coach_title": "Owner",
        "timezone": "Europe/London",
        "units": "lb",
        **overrides,
    }


def test_settings_page_has_gym_tracked_lifts_and_week_types(coach_client):
    html = coach_client.get("/coach/settings/").content.decode()
    assert 'id="trackedLifts"' in html and 'id="weekTypes"' in html
    for name in ["Accumulation", "Intensification", "Comp Prep", "Deload", "Cutting", "Technique"]:
        assert name in html


def test_saving_settings(coach_client, coach):
    response = coach_client.post("/coach/settings/", form())
    assert response["Location"] == "/coach/settings/"
    gym = Gym.objects.get(pk=coach.gym.pk)
    coach.refresh_from_db()
    assert (gym.name, gym.timezone, gym.units, coach.title) == (
        "Iron Ridge WL",
        "Europe/London",
        "lb",
        "Owner",
    )
    assert "Settings saved" in coach_client.get("/coach/settings/").content.decode()  # shown as a toast


def test_invalid_settings_are_rejected(coach_client, coach):
    html = coach_client.post("/coach/settings/", form(timezone="Mars/Base")).content.decode()
    assert "errorlist" in html
    coach.gym.refresh_from_db()
    assert coach.gym.timezone == "America/New_York"
