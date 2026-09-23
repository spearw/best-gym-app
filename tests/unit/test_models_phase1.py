import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts import units
from apps.accounts.models import Athlete, BodyweightEntry, Gym, Invite, InviteStatus, MaxEntry
from apps.exercises.models import Exercise
from apps.exercises.starter import install_pack

from ..conftest import cat

pytestmark = pytest.mark.django_db


def test_units_round_trip_and_display():
    assert units.to_kg("100", "kg") == Decimal("100.00")
    assert units.to_kg("225", "lb") == Decimal("102.06")
    assert units.from_kg(Decimal("102.06"), "lb") == Decimal("225.0")
    assert units.display(Decimal("82.50"), "kg") == "82.5 kg"
    assert units.display(None, "kg") == ""


def test_installing_a_pack_twice_changes_nothing(gym):
    install_pack(gym, "weightlifting")  # second run (fixture already ran it once)
    assert Exercise.objects.filter(gym=gym).count() == 24
    assert gym.categories.count() == 8 and gym.tags.count() == 13 and gym.week_types.count() == 6
    fsq = Exercise.objects.get(gym=gym, key="fsq")
    assert fsq.max_source.key == "bsq"
    snatch = Exercise.objects.get(gym=gym, key="sn")
    assert snatch.percent_of is None and snatch.max_source == snatch


def test_reinstalling_never_undoes_a_coaches_edits(gym):
    fsq = Exercise.objects.get(gym=gym, key="fsq")
    fsq.name, fsq.percent_of = "Front Squat (own max)", None
    fsq.save()
    fsq.tags.clear()
    mine = Exercise.objects.create(gym=gym, name="Sandbag carry", category=cat(gym, "Accessory"))
    install_pack(gym, "weightlifting")
    fsq.refresh_from_db()
    assert fsq.name == "Front Squat (own max)" and fsq.percent_of is None and not fsq.tags.exists()
    mine.refresh_from_db()
    assert mine.name == "Sandbag carry" and mine.key == ""


def test_exercise_key_unique_per_gym_but_blank_keys_repeat(gym):
    other = Gym.objects.create(name="Other")
    install_pack(other, "weightlifting")  # same keys in another gym are fine
    accessory = cat(gym, "Accessory")
    Exercise.objects.create(gym=gym, name="A", category=accessory)
    Exercise.objects.create(gym=gym, name="B", category=accessory)  # two blank keys are fine
    with pytest.raises(IntegrityError):
        Exercise.objects.create(gym=gym, name="Snatch again", category=cat(gym, "Snatch"), key="sn")


def test_an_exercise_must_use_its_own_gyms_category(gym):
    other = Gym.objects.create(name="Other")
    install_pack(other, "empty")
    ex = Exercise(gym=gym, name="Crossed", category=cat(other, "Strength"))
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
