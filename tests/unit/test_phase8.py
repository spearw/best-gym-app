"""Phase 8: form videos, the morning digest, units, the installable app, error pages and
rate limits."""

import datetime
import json
import zoneinfo

import pytest
from django.core import mail
from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone

from apps.dashboard import alerts, digest
from apps.exercises.models import Exercise
from apps.messaging.models import Message
from apps.programs import services as program_services
from apps.programs.models import WeekType
from apps.workouts import sessions, videos
from apps.workouts.models import FormVideo

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}
MB = 1024 * 1024


@pytest.fixture
def log(athlete, coach):
    week_type = WeekType.objects.get(gym=coach.gym, name="Accumulation")
    program = program_services.start_program(athlete, "Block", athlete.today(), 1, week_type, by=coach.user)
    day = program.weeks.get().days.get(date=athlete.today())
    program_services.add_prescription(day, Exercise.objects.get(gym=coach.gym, key="sn"), athlete)
    return sessions.start(athlete, day.sessions.get())


@pytest.fixture
def stored(monkeypatch):
    """Pretend the bucket holds whatever was signed for (no network in unit tests)."""
    deleted = []
    monkeypatch.setattr(videos, "stored_size", lambda key: FormVideo.objects.get(key=key).size)
    monkeypatch.setattr(videos, "delete", lambda key: deleted.append(key))
    monkeypatch.setattr(videos, "view_url", lambda key: f"https://bucket.example/{key}?signed")
    return deleted


def upload(client, log, size=5 * MB, content_type="video/mp4"):
    se = log.exercises.get()
    return client.post(
        f"/app/log/{log.pk}/videos/start/", {"se": se.pk, "size": size, "content_type": content_type}
    )


# ---------------------------------------------------------------- form videos


def test_upload_is_signed_for_exactly_that_file(athlete_client, log):
    started = upload(athlete_client, log).json()
    assert "X-Amz-Signature" in started["url"] and "content-length" in started["url"].lower()
    video = FormVideo.objects.get()
    assert (
        video.key.startswith(f"form-videos/{log.athlete.gym_id}/{log.athlete.pk}/")
        and video.uploaded_at is None
    )
    assert upload(athlete_client, log, size=201 * MB).status_code == 400  # over the limit
    assert upload(athlete_client, log, content_type="image/png").json()["error"] == "That file isn't a video."


def test_confirming_notifies_the_coach(athlete_client, log, coach, stored):
    started = upload(athlete_client, log).json()
    response = athlete_client.post(started["done_url"], **HX)
    assert "Video sent" in json.loads(response["HX-Trigger"])["toast"]["message"]
    video = FormVideo.objects.get()
    assert video.uploaded_at is not None
    athlete_client.post(f"/app/log/{log.pk}/videos/{video.pk}/note/", {"note": "Is my dip vertical?"}, **HX)
    row = alerts.feed(coach).get(kind="video")
    assert row.text == "Uploaded a form video: Snatch — “Is my dip vertical?”"
    assert alerts.link_for(row).endswith(f"/sessions/#video-{video.pk}")


def test_an_upload_that_never_arrived_is_not_confirmed(athlete_client, log, monkeypatch):
    started = upload(athlete_client, log).json()
    monkeypatch.setattr(videos, "stored_size", lambda key: None)
    assert athlete_client.post(started["done_url"], **HX).status_code == 400
    assert FormVideo.objects.get().uploaded_at is None


def test_uploads_are_capped_per_exercise_and_closed_sessions_refuse(athlete_client, log, stored):
    for _ in range(3):
        athlete_client.post(upload(athlete_client, log).json()["done_url"], **HX)
    assert "Up to 3 videos" in upload(athlete_client, log).json()["error"]
    FormVideo.objects.all().delete()
    sessions.finish(log, 7, "")
    log.finished_at = timezone.now() - datetime.timedelta(hours=30)
    log.save()
    assert upload(athlete_client, log).status_code == 400


def test_videos_are_off_without_storage(athlete_client, log, settings):
    settings.FORM_VIDEOS = {**settings.FORM_VIDEOS, "endpoint": ""}
    assert upload(athlete_client, log).status_code == 400
    assert "Add a form video" not in athlete_client.get(f"/app/log/{log.pk}/exercise/1/").content.decode()


def test_athlete_can_remove_before_review(athlete_client, log, coach, stored):
    athlete_client.post(upload(athlete_client, log).json()["done_url"], **HX)
    video = FormVideo.objects.get()
    athlete_client.post(f"/app/log/{log.pk}/videos/{video.pk}/remove/", **HX)
    assert not FormVideo.objects.exists() and stored == [video.key]
    assert not alerts.feed(coach).filter(kind="video").exists()


def test_coach_review_sends_feedback_to_messages(athlete_client, coach, log, stored):
    athlete_client.post(upload(athlete_client, log).json()["done_url"], **HX)
    video = FormVideo.objects.get()
    coach_client = Client()
    coach_client.force_login(coach.user)
    athlete = log.athlete
    modal = coach_client.get(f"/coach/athletes/{athlete.pk}/videos/{video.pk}/", **HX).content.decode()
    assert "<video" in modal and "https://bucket.example/" in modal
    response = coach_client.post(
        f"/coach/athletes/{athlete.pk}/videos/{video.pk}/", {"feedback": "Stay over the bar longer."}, **HX
    )
    assert json.loads(response["HX-Trigger"])["toast"]["message"] == "Feedback sent to Maya"
    video.refresh_from_db()
    assert video.reviewed_at and video.feedback == "Stay over the bar longer."
    message = Message.objects.get()
    assert message.sender == coach.user and message.body.startswith("Form check — Snatch (")
    assert not alerts.feed(coach).filter(kind="video", cleared_at__isnull=True).exists()
    html = coach_client.get(f"/coach/athletes/{athlete.pk}/sessions/").content.decode()
    assert f'id="video-{video.pk}"' in html and "reviewed" in html


def test_other_coaches_cannot_watch(log, athlete_client, stored, make_user, gym):
    from apps.accounts.models import Coach

    athlete_client.post(upload(athlete_client, log).json()["done_url"], **HX)
    other = Coach.objects.create(user=make_user("sam@example.com", "Sam"), gym=gym)
    client = Client()
    client.force_login(other.user)
    video = FormVideo.objects.get()
    assert client.get(f"/coach/athletes/{log.athlete.pk}/videos/{video.pk}/").status_code == 404


def test_videos_expire_after_the_keep_period(athlete_client, log, stored):
    athlete_client.post(upload(athlete_client, log).json()["done_url"], **HX)
    upload(athlete_client, log)  # started, never finished
    FormVideo.objects.filter(uploaded_at__isnull=False).update(
        uploaded_at=timezone.now() - datetime.timedelta(days=91)
    )
    FormVideo.objects.filter(uploaded_at__isnull=True).update(
        created_at=timezone.now() - datetime.timedelta(days=2)
    )
    assert videos.expire() == (1, 1)
    kept = FormVideo.objects.get()
    assert kept.deleted_at is not None and len(stored) == 2


# ---------------------------------------------------------------- the digest


def _at_gym_hour(coach, hour, day_offset=0):
    zone = zoneinfo.ZoneInfo(coach.gym.timezone)
    today = timezone.now().astimezone(zone).date() + datetime.timedelta(days=day_offset)
    return datetime.datetime.combine(today, datetime.time(hour, 5), tzinfo=zone)


def test_digest_goes_at_seven_with_new_items_only(coach, athlete):
    from apps.dashboard.models import Notification

    alerts.sync_athlete(athlete)  # no program + missing metrics
    # Raised the evening before this test's "7am", so they count as new then.
    Notification.objects.update(created_at=_at_gym_hour(coach, 7) - datetime.timedelta(hours=10))
    assert digest.send(coach, _at_gym_hour(coach, 6)) == 0  # not 7am yet
    assert digest.send(coach, _at_gym_hour(coach, 7)) == 2
    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert email.subject.startswith("2 new things need your attention") and "Maya Torres" in email.body
    assert "/coach/athletes/" in email.body and "Turn it off in Settings" in email.body
    assert digest.send(coach, _at_gym_hour(coach, 7)) == 0  # once a day
    coach.refresh_from_db()
    assert coach.last_digest_at is not None
    assert digest.send(coach, _at_gym_hour(coach, 7, day_offset=1)) == 0  # nothing new since
    assert len(mail.outbox) == 1


def test_digest_can_be_turned_off(coach_client, coach, athlete):
    form = {
        "gym_name": coach.gym.name,
        "coach_title": "Owner",
        "timezone": coach.gym.timezone,
        "units": "kg",
        "week_start": "0",
    }
    coach_client.post("/coach/settings/", form)  # "digest" unticked
    coach.refresh_from_db()
    assert coach.digest is False
    alerts.sync_athlete(athlete)
    assert digest.send(coach, _at_gym_hour(coach, 7)) == 0 and not mail.outbox


def test_cron_command_runs_everything(coach, athlete, capsys):
    call_command("cron")
    out = capsys.readouterr().out
    assert "synced alerts" in out and "digest(s) sent" in out


# ---------------------------------------------------------------- units, the app, errors


def test_athlete_switches_units(athlete_client, athlete):
    response = athlete_client.post("/app/profile/units/", {"units": "lb"})
    assert response["Location"] == "/app/profile/"
    athlete.refresh_from_db()
    assert athlete.units == "lb"
    assert "Weights now show in pounds" in athlete_client.get("/app/profile/").content.decode()


def test_manifest_and_service_worker(client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest["Content-Type"] == "application/manifest+json"
    data = manifest.json()
    assert data["start_url"] == "/app/" and data["display"] == "standalone"
    assert {i["sizes"] for i in data["icons"]} == {"192x192", "512x512"}
    sw = client.get("/sw.js")
    assert sw["Content-Type"] == "application/javascript" and b"/offline/" in sw.content
    assert b"__VERSION__" not in sw.content and b"platform-" in sw.content
    assert "You're offline" in client.get("/offline/").content.decode()


@override_settings(DEBUG=False)
def test_error_pages(client):
    response = client.get("/no-such-page/")
    assert response.status_code == 404 and "Page not found" in response.content.decode()


# ---------------------------------------------------------------- rate limits


def test_sign_in_is_rate_limited(client, athlete):
    for _ in range(10):
        client.post("/accounts/login/", {"username": "maya@example.com", "password": "wrong"})
    response = client.post("/accounts/login/", {"username": "maya@example.com", "password": "wrong"})
    assert response.status_code == 429 and "Too many sign-in attempts" in response.content.decode()
    other = client.post("/accounts/login/", {"username": "someone@example.com", "password": "wrong"})
    assert other.status_code == 200  # a different email isn't blocked


def test_messages_are_rate_limited(athlete_client):
    for i in range(30):
        athlete_client.post("/app/coach/send/", {"body": f"msg {i}"}, **HX)
    response = athlete_client.post("/app/coach/send/", {"body": "one too many"}, **HX)
    assert response.status_code == 429 and "Too many" in response["HX-Trigger"]
    assert Message.objects.count() == 30
