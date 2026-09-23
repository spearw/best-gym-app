import pytest

from apps.accounts.models import Gym

pytestmark = pytest.mark.django_db


def form(**overrides):
    data = {
        "gym_name": "Iron Ridge WL",
        "coach_title": "Owner",
        "timezone": "Europe/London",
        "units": "lb",
        "colour_accum": "#2E9E5B",
        "colour_intens": "#E07C24",
        "colour_peak": "#D8412F",
        "colour_deload": "#8A63D2",
        "colour_cut": "#2B7DE0",
        "colour_tech": "#0F9BA8",
    }
    data.update(overrides)
    return data


def test_settings_page_shows_week_type_legend(coach_client):
    html = coach_client.get("/coach/settings/").content.decode()
    for label in ["Accumulation", "Intensification", "Comp Prep", "Deload", "Cutting", "Technique"]:
        assert label in html
    assert 'type="color"' in html


def test_saving_settings(coach_client, coach):
    response = coach_client.post("/coach/settings/", form(colour_peak="#aa0000"))
    assert response["Location"] == "/coach/settings/"
    gym = Gym.objects.get(pk=coach.gym.pk)
    coach.refresh_from_db()
    assert (gym.name, gym.timezone, gym.units, coach.title) == (
        "Iron Ridge WL",
        "Europe/London",
        "lb",
        "Owner",
    )
    assert gym.week_type_colours == {"peak": "#AA0000"}  # only changed colours are stored
    html = coach_client.get("/coach/settings/").content.decode()
    assert "--wk-peak:#AA0000" in html  # applied site-wide as a CSS variable
    assert "Settings saved" in html  # message shown as a toast


def test_reset_colours(coach_client, coach):
    coach.gym.week_type_colours = {"peak": "#AA0000"}
    coach.gym.save()
    coach_client.post("/coach/settings/", form(reset_colours="1", colour_peak="#aa0000"))
    coach.gym.refresh_from_db()
    assert coach.gym.week_type_colours == {}


def test_invalid_settings_are_rejected(coach_client, coach):
    html = coach_client.post(
        "/coach/settings/", form(timezone="Mars/Base", colour_tech="blue")
    ).content.decode()
    assert html.count("errorlist") >= 2
    coach.gym.refresh_from_db()
    assert coach.gym.timezone == "America/New_York"
