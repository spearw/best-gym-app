"""Shared fixtures: a gym with the starter library, a coach, and an athlete of that coach."""

import pytest

from apps.accounts.models import Athlete, Coach, Gym, User
from apps.exercises.starter import install_pack

PASSWORD = "correct-horse-battery-9"


@pytest.fixture
def gym(db):
    gym = Gym.objects.create(name="Iron Ridge Weightlifting", timezone="America/New_York")
    install_pack(gym, "weightlifting")  # the mockup's library; tracks snatch, C&J, back squat
    return gym


@pytest.fixture
def make_user(db):
    def make(email, name="", **extra):
        return User.objects.create_user(email, PASSWORD, name=name, **extra)

    return make


@pytest.fixture
def coach(gym, make_user):
    return Coach.objects.create(user=make_user("dana@example.com", "Dana Whitfield"), gym=gym)


@pytest.fixture
def athlete(coach, make_user):
    user = make_user("maya@example.com", "Maya Torres", timezone="America/New_York")
    return Athlete.objects.create(user=user, coach=coach, gym=coach.gym)


@pytest.fixture
def coach_client(client, coach):
    client.force_login(coach.user)
    return client


@pytest.fixture
def athlete_client(client, athlete):
    client.force_login(athlete.user)
    return client


def lift_field(gym, key):
    """The form/URL key for a starter lift in this gym, e.g. lift_field(gym, "sn") -> "lift_12"."""
    from apps.exercises.models import Exercise

    return f"lift_{Exercise.objects.get(gym=gym, key=key).pk}"


def cat(gym, name):
    """A gym's category by name (case-insensitive)."""
    from apps.exercises.models import Category

    return Category.objects.get(gym=gym, name__iexact=name)


def tag_ids(gym, *names):
    """Primary keys of a gym's tags by name, in the order given."""
    from apps.exercises.models import Tag

    by_name = {t.name.lower(): t.pk for t in Tag.objects.filter(gym=gym)}
    return [by_name[n.lower()] for n in names]
