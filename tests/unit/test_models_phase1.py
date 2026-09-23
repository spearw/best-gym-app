import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts import units
from apps.accounts.models import Athlete, BodyweightEntry, Gym, Invite, InviteStatus, MaxEntry
from apps.exercises.models import Exercise
from apps.exercises.starter import STARTER_EXERCISES, install_starter_library

pytestmark = pytest.mark.django_db


def test_units_round_trip_and_display():
    assert units.to_kg("100", "kg") == Decimal("100.00")
    assert units.to_kg("225", "lb") == Decimal("102.06")
    assert units.from_kg(Decimal("102.06"), "lb") == Decimal("225.0")
    assert units.display(Decimal("82.50"), "kg") == "82.5 kg"
    assert units.display(None, "kg") == ""


def test_starter_library_is_idempotent_and_maps_percent_of(gym):
    install_starter_library(gym)  # second run (fixture already ran it once)
    assert Exercise.objects.filter(gym=gym).count() == len(STARTER_EXERCISES) == 24
    fsq = Exercise.objects.get(gym=gym, key="fsq")
    assert fsq.max_source.key == "bsq"
    snatch = Exercise.objects.get(gym=gym, key="sn")
    assert snatch.percent_of is None and snatch.max_source == snatch


def test_starter_library_leaves_coach_exercises_alone(gym):
    mine = Exercise.objects.create(gym=gym, name="Sandbag carry", category="accessory")
    install_starter_library(gym)
    mine.refresh_from_db()
    assert mine.name == "Sandbag carry" and mine.key == ""


def test_exercise_key_unique_per_gym_but_blank_keys_repeat(gym):
    other = Gym.objects.create(name="Other")
    install_starter_library(other)  # same keys in another gym are fine
    Exercise.objects.create(gym=gym, name="A", category="accessory")
    Exercise.objects.create(gym=gym, name="B", category="accessory")  # two blank keys are fine
    with pytest.raises(IntegrityError):
        Exercise.objects.create(gym=gym, name="Snatch again", category="snatch", key="sn")


def test_exercise_tags_must_come_from_the_fixed_list(gym):
    ex = Exercise(gym=gym, name="Weird", category="accessory", tags=["strength", "made-up"])
    with pytest.raises(ValidationError):
        ex.full_clean()


def test_latest_max_and_bodyweight_win(athlete):
    snatch = Exercise.objects.get(gym=athlete.gym, key="sn")
    today = datetime.date(2026, 9, 1)
    MaxEntry.objects.create(athlete=athlete, exercise=snatch, date=today, kg=80, source="onboarding")
    MaxEntry.objects.create(
        athlete=athlete, exercise=snatch, date=today + datetime.timedelta(days=5), kg=82, source="session"
    )
    BodyweightEntry.objects.create(athlete=athlete, date=today, kg=64, source="athlete")
    BodyweightEntry.objects.create(
        athlete=athlete, date=today + datetime.timedelta(days=2), kg="63.8", source="athlete"
    )
    assert athlete.current_max(snatch).kg == 82
    assert athlete.current_maxes()[snatch.pk].kg == 82
    assert athlete.current_bodyweight().kg == Decimal("63.8")


def test_today_uses_the_persons_time_zone(athlete, monkeypatch):
    # 02:30 UTC on 24 Sep is still 23 Sep in New York.
    fixed = datetime.datetime(2026, 9, 24, 2, 30, tzinfo=datetime.UTC)
    monkeypatch.setattr(timezone, "now", lambda: fixed)
    assert athlete.today() == datetime.date(2026, 9, 23)
    athlete.user.timezone = "Europe/Berlin"
    assert athlete.today() == datetime.date(2026, 9, 24)


def test_archived_athlete_is_not_an_athlete_profile(athlete):
    assert athlete.user.athlete_profile == athlete
    athlete.archived_at = timezone.now()
    athlete.save()
    athlete.user.refresh_from_db()
    assert athlete.user.athlete_profile is None


def test_week_type_colour_overrides_are_validated(gym):
    gym.week_type_colours = {"accum": "#123456"}
    gym.full_clean()
    assert next(w for w in gym.week_types() if w["key"] == "accum")["colour"] == "#123456"
    gym.week_type_colours = {"accum": "red"}
    with pytest.raises(ValidationError):
        gym.full_clean()
    gym.week_type_colours = {"nope": "#123456"}
    with pytest.raises(ValidationError):
        gym.full_clean()


def test_invite_usability(coach):
    invite = Invite.objects.create(coach=coach)
    assert invite.is_usable and len(invite.token) >= 20
    invite.expires_at = timezone.now() - datetime.timedelta(seconds=1)
    assert not invite.is_usable
    invite.expires_at = timezone.now() + datetime.timedelta(days=1)
    invite.status = InviteStatus.REVOKED
    assert not invite.is_usable


def test_measurements_must_be_positive(athlete):
    with pytest.raises(IntegrityError):
        BodyweightEntry.objects.create(athlete=athlete, date=datetime.date.today(), kg=0, source="athlete")


def test_one_user_can_be_coach_and_athlete(coach):
    Athlete.objects.create(user=coach.user, coach=coach, gym=coach.gym)
    coach.user.refresh_from_db()
    assert coach.user.coach_profile and coach.user.athlete_profile
