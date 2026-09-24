"""Fixes from the security audit (24 September): sign-in limits (also on the admin's
sign-in), ended programs, archived athletes joining, malformed modal posts, and message
threads fetched by another site."""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from apps.accounts.models import Invite
from apps.exercises.models import Exercise
from apps.library import services as library_services
from apps.library.models import TemplateKind
from apps.messaging.models import Message, Thread
from apps.programs import services as program_services
from apps.programs.models import WeekType

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def sign_in(client, email, ip):
    return client.post("/accounts/login/", {"username": email, "password": "wrong"}, HTTP_X_FORWARDED_FOR=ip)


def test_one_address_cannot_spray_many_accounts(client, athlete):
    for i in range(50):
        assert sign_in(client, f"person{i}@example.com", "203.0.113.5").status_code == 200
    assert sign_in(client, "maya@example.com", "203.0.113.5").status_code == 429
    assert sign_in(client, "maya@example.com", "203.0.113.6").status_code == 200  # another address is fine


def test_many_addresses_cannot_guess_one_account(client, athlete):
    for i in range(30):
        assert sign_in(client, "maya@example.com", f"198.51.100.{i}").status_code == 200
    assert sign_in(client, "maya@example.com", "198.51.100.200").status_code == 429


def test_admin_sign_in_is_limited_too(client, athlete):
    url = f"/{settings.ADMIN_PATH}login/"
    assert client.get(url).status_code == 200
    for _ in range(10):
        client.post(
            url, {"username": "maya@example.com", "password": "wrong"}, HTTP_X_FORWARDED_FOR="192.0.2.9"
        )
    response = client.post(
        url, {"username": "maya@example.com", "password": "wrong"}, HTTP_X_FORWARDED_FOR="192.0.2.9"
    )
    assert response.status_code == 429


def test_sessions_of_an_ended_program_cannot_be_started(athlete_client, athlete, coach):
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    old = program_services.start_program(athlete, "Old", athlete.today(), 1, week_type, by=coach.user)
    week = old.weeks.get()
    program_services.set_published(week, True)
    day = week.days.get(date=athlete.today())
    program_services.add_prescription(day, Exercise.objects.get(gym=coach.gym, key="sn"), athlete)
    session = day.sessions.get()
    program_services.start_program(athlete, "New", athlete.today(), 1, week_type, by=coach.user)
    assert athlete_client.post(reverse("app:start", args=[session.pk])).status_code == 404


def test_an_archived_athlete_joining_again_gets_a_message_not_an_error(client, athlete, coach):
    from django.utils import timezone

    athlete.archived_at = timezone.now()
    athlete.save()
    client.force_login(athlete.user)
    invite = Invite.objects.create(coach=coach)
    response = client.post(f"/join/{invite.token}/")
    assert response.status_code == 302 and response["Location"] == reverse("accounts:no_profile")


def test_malformed_slot_posts_are_form_errors(coach_client, coach):
    template = library_services.new_template(coach.gym, TemplateKind.PROGRAM, coach.user)
    slot = library_services.add_slot(
        template.weeks.get().sessions.first(), Exercise.objects.get(gym=coach.gym, key="sn")
    )
    response = coach_client.post(
        reverse("coach:template_slot_edit", args=[template.pk, slot.pk]),
        {
            "kind": "');alert(1);('",
            "exercise": "abc",
            "default": "x",
            "sets": "3",
            "load_basis": "');alert(1);('",
        },
        **HX,
    )
    assert response.status_code == 200
    html = response.content.decode()
    assert "alert(1)" not in html  # nothing posted ends up inside the Alpine expressions


def test_rx_modal_does_not_echo_a_bad_load_basis(coach_client, athlete, coach):
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    program = program_services.start_program(athlete, "P", athlete.today(), 1, week_type, by=coach.user)
    day = program.weeks.get().days.first()
    rx = program_services.add_prescription(day, Exercise.objects.get(gym=coach.gym, key="sn"), athlete)
    response = coach_client.post(
        reverse("coach:rx_edit", args=[athlete.pk, rx.pk]),
        {"sets": "3", "load_basis": "');alert(1);('"},
        **HX,
    )
    assert "alert(1)" not in response.content.decode()


def test_another_site_fetching_the_thread_does_not_mark_it_read(athlete, coach):
    thread = Thread.for_athlete(athlete)
    Message.objects.create(thread=thread, sender=coach.user, body="Hi")
    client = Client()
    client.force_login(athlete.user)
    client.get(reverse("app:message_thread"), HTTP_SEC_FETCH_SITE="cross-site")
    assert Message.objects.get().read_at is None
    client.get(reverse("app:message_thread"), HTTP_SEC_FETCH_SITE="same-origin")
    assert Message.objects.get().read_at is not None
