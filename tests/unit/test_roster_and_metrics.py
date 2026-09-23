import json
import re
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import Athlete, BodyweightEntry, Coach, MaxEntry
from apps.exercises.models import Exercise

from ..conftest import lift_field

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def other_coach_athlete(coach, make_user):
    other = Coach.objects.create(user=make_user("coach2@example.com", "Coach Two"), gym=coach.gym)
    return Athlete.objects.create(
        user=make_user("theirs@example.com", "Not Yours"), coach=other, gym=coach.gym
    )


def test_roster_cards_show_own_athletes_with_missing_counts(coach_client, athlete, other_coach_athlete):
    html = coach_client.get("/coach/athletes/").content.decode()
    assert "Maya Torres" in html and "6 metrics missing" in html
    assert "Not Yours" not in html


def test_roster_filter_returns_cards_only(coach_client, athlete):
    html = coach_client.get(
        "/coach/athletes/", {"q": "may"}, HTTP_HX_TARGET="clientCards", **HX
    ).content.decode()
    assert "Maya Torres" in html and "Pending invites" not in html
    html = coach_client.get(
        "/coach/athletes/", {"q": "zzz"}, HTTP_HX_TARGET="clientCards", **HX
    ).content.decode()
    assert "No athletes match" in html


def test_archived_athletes_leave_the_roster(coach_client, athlete):
    athlete.archived_at = timezone.now()
    athlete.save()
    assert "Maya Torres" not in coach_client.get("/coach/athletes/").content.decode()
    assert coach_client.get(f"/coach/athletes/{athlete.pk}/metrics/").status_code == 404


@pytest.mark.parametrize(
    "tab,text",
    [
        ("overview", "arrives in phase 7"),
        ("program", "Start a program for Maya"),
        ("sessions", "arrives in phase 4"),
        ("messages", "arrives in phase 6"),
    ],
)
def test_detail_tabs_are_urls(coach_client, athlete, tab, text):
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/{tab}/").content.decode()
    assert text in html and f'class="active" href="/coach/athletes/{athlete.pk}/{tab}/"' in html
    assert "Maya Torres" in html


def test_other_coaches_athletes_are_404(coach_client, other_coach_athlete):
    pk = other_coach_athlete.pk
    for url in [
        f"/coach/athletes/{pk}/metrics/",
        f"/coach/athletes/{pk}/metrics/{lift_field(other_coach_athlete.gym, 'sn')}/edit/",
        f"/coach/athletes/{pk}/questions/",
    ]:
        assert coach_client.get(url, **HX).status_code == 404, url
    assert coach_client.post(f"/coach/athletes/{pk}/remind/", **HX).status_code == 404


def test_metrics_tab_shows_values_in_gym_units(coach_client, coach, athlete):
    sn = Exercise.objects.get(gym=coach.gym, key="sn")
    MaxEntry.objects.create(
        athlete=athlete, exercise=sn, date="2026-09-01", kg=Decimal("100"), source="onboarding"
    )
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/metrics/").content.decode()
    assert "100 kg" in html and "not provided — athlete skipped" in html
    coach.gym.units = "lb"
    coach.gym.save()
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/metrics/").content.decode()
    assert "220.5 lb" in html  # header stat and card both convert


def test_coach_adds_a_max_as_a_new_history_row(coach_client, coach, athlete):
    response = coach_client.post(
        f"/coach/athletes/{athlete.pk}/metrics/{lift_field(coach.gym, 'cj')}/edit/",
        {"value": "105", "date": "2026-09-10"},
        **HX,
    )
    assert response["HX-Retarget"] == "#metricsPanel"
    assert json.loads(response["HX-Trigger"])["toast"]["message"] == "Clean & Jerk 1RM saved"
    # Closing the modal must wait until the panel is swapped in, or HTMX drops the swap.
    assert json.loads(response["HX-Trigger-After-Swap"]) == {"closeModal": True}
    html = response.content.decode()
    assert 'id="cdStats" hx-swap-oob="true"' in html and "105 kg" in html
    entry = MaxEntry.objects.get(athlete=athlete)
    assert (entry.kg, str(entry.date), entry.source) == (Decimal("105.00"), "2026-09-10", "coach")


def test_coach_entry_in_pounds_is_stored_in_kg(coach_client, coach, athlete):
    coach.gym.units = "lb"
    coach.gym.save()
    coach_client.post(
        f"/coach/athletes/{athlete.pk}/metrics/bodyweight/edit/",
        {"value": "141", "date": athlete.today().isoformat()},
        **HX,
    )
    assert BodyweightEntry.objects.get(athlete=athlete).kg == Decimal("63.96")


def test_height_and_years_replace_the_value(coach_client, athlete):
    coach_client.post(f"/coach/athletes/{athlete.pk}/metrics/height_cm/edit/", {"value": "170"}, **HX)
    coach_client.post(f"/coach/athletes/{athlete.pk}/metrics/years_training/edit/", {"value": "5+"}, **HX)
    athlete.refresh_from_db()
    assert athlete.height_cm == Decimal("170.0") and athlete.years_training == "5+"


def test_metric_edit_validation_rerenders_the_modal(coach_client, athlete):
    response = coach_client.post(
        f"/coach/athletes/{athlete.pk}/metrics/{lift_field(athlete.gym, 'sn')}/edit/",
        {"value": "-4", "date": "2999-01-01"},
        **HX,
    )
    html = response.content.decode()
    assert "HX-Retarget" not in response and 'class="modal open"' in html
    assert "in the future" in html and MaxEntry.objects.count() == 0
    assert coach_client.get(f"/coach/athletes/{athlete.pk}/metrics/nope/edit/", **HX).status_code == 404


def test_remind_emails_the_missing_fields(coach_client, athlete):
    response = coach_client.post(f"/coach/athletes/{athlete.pk}/remind/", **HX)
    assert json.loads(response["HX-Trigger"])["toast"]["message"] == "Reminder emailed to Maya"
    assert mail.outbox[0].to == ["maya@example.com"]
    body = mail.outbox[0].body
    assert "Snatch 1RM" in body and "Years training" in body
    assert "http://testserver/app/profile/numbers/" in body


def test_remind_with_nothing_missing(coach_client, coach, athlete):
    for key in ["sn", "cj", "bsq"]:
        MaxEntry.objects.create(
            athlete=athlete,
            exercise=Exercise.objects.get(gym=coach.gym, key=key),
            date="2026-09-01",
            kg=100,
            source="coach",
        )
    BodyweightEntry.objects.create(athlete=athlete, date="2026-09-01", kg=64, source="coach")
    athlete.height_cm, athlete.years_training = 168, "3-5"
    athlete.save()
    response = coach_client.post(f"/coach/athletes/{athlete.pk}/remind/", **HX)
    assert "has filled in everything" in json.loads(response["HX-Trigger"])["toast"]["message"]
    assert len(mail.outbox) == 0


def test_athlete_fills_only_missing_numbers(athlete_client, athlete, coach):
    BodyweightEntry.objects.create(athlete=athlete, date="2026-09-01", kg=64, source="coach")
    html = athlete_client.get("/app/profile/numbers/").content.decode()
    assert "Bodyweight" not in html and "Snatch 1RM" in html
    response = athlete_client.post(
        "/app/profile/numbers/", {lift_field(coach.gym, "sn"): "80", "years_training": "1-3"}
    )
    assert response["Location"] == "/app/profile/"
    assert MaxEntry.objects.get(athlete=athlete).source == "athlete"
    profile = athlete_client.get("/app/profile/").content.decode()
    assert "Dana can see your numbers" in profile  # shown as a toast
    assert "Add missing numbers (3)" in profile


def test_numbers_page_with_nothing_missing_goes_back_to_profile(athlete_client, athlete, coach):
    for key in ["sn", "cj", "bsq"]:
        MaxEntry.objects.create(
            athlete=athlete,
            exercise=Exercise.objects.get(gym=coach.gym, key=key),
            date="2026-09-01",
            kg=100,
            source="coach",
        )
    BodyweightEntry.objects.create(athlete=athlete, date="2026-09-01", kg=64, source="coach")
    athlete.height_cm, athlete.years_training = 168, "3-5"
    athlete.save()
    assert athlete_client.get("/app/profile/numbers/")["Location"] == "/app/profile/"


def test_recent_measurements_list(coach_client, coach, athlete):
    BodyweightEntry.objects.create(athlete=athlete, date="2026-09-01", kg=64, source="athlete")
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/metrics/").content.decode()
    assert re.search(r"Recent measurements.*Bodyweight.*64 kg", html, re.S)
