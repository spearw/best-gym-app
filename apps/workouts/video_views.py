"""Form videos: the athlete uploads a clip from the session player; the coach watches it
on the athlete's Sessions tab, writes feedback (sent into their message thread) and marks
it reviewed. Storage is in videos.py; the bytes never pass through Django."""

from django import forms
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts.access import athlete_required, coach_required
from apps.accounts.coach_views import coach_athlete
from apps.dashboard import alerts
from apps.ratelimit import by_user, rate_limit

from . import videos
from .models import FormVideo, SessionLog

MAX_PER_EXERCISE = 3


def _log(request, log_id):
    return get_object_or_404(SessionLog, pk=log_id, athlete=request.athlete)


def video_context(se, editable):
    return {
        "se": se,
        "log": se.session_log,
        "form_videos": [v for v in se.videos.all() if v.uploaded_at],
        "can_upload": editable and videos.enabled() and se.videos.uploaded().count() < MAX_PER_EXERCISE,
        "max_mb": videos.config()["max_bytes"] // (1024 * 1024),
        "coach_name": se.session_log.athlete.coach.user.get_short_name(),
    }


def _card(request, se, message=None, kind=""):
    response = TemplateResponse(request, "app/_videos.html", video_context(se, se.session_log.editable()))
    return hx.toast(response, message, kind) if message else response


# ---------------------------------------------------------------- athlete


class StartForm(forms.Form):
    se = forms.IntegerField()
    size = forms.IntegerField(min_value=1)
    content_type = forms.CharField(max_length=60)


@athlete_required
@require_POST
@rate_limit("video", 20, 60 * 60, key=by_user)
def start(request, log_id):
    """Sign an upload for one clip; the browser then PUTs the file straight to the bucket."""
    log = _log(request, log_id)
    form = StartForm(request.POST)
    if not videos.enabled() or not log.editable() or not form.is_valid():
        return JsonResponse({"error": "Videos can't be added to this session."}, status=400)
    d = form.cleaned_data
    se = get_object_or_404(log.exercises, pk=d["se"])
    max_bytes = videos.config()["max_bytes"]
    if d["size"] > max_bytes:
        mb = max_bytes // (1024 * 1024)
        return JsonResponse(
            {"error": f"That video is over {mb} MB — trim it to a minute or two."}, status=400
        )
    if not d["content_type"].startswith("video/"):
        return JsonResponse({"error": "That file isn't a video."}, status=400)
    if se.videos.uploaded().count() >= MAX_PER_EXERCISE:
        return JsonResponse({"error": f"Up to {MAX_PER_EXERCISE} videos per exercise."}, status=400)
    key = videos.new_key(request.athlete, d["content_type"])
    video = FormVideo.objects.create(
        session_log=log,
        session_exercise=se,
        exercise_name=se.exercise_name,
        key=key,
        content_type=d["content_type"],
        size=d["size"],
    )
    return JsonResponse(
        {
            "id": video.pk,
            "url": videos.upload_url(key, d["size"], d["content_type"]),
            "done_url": f"/app/log/{log.pk}/videos/{video.pk}/done/",
        }
    )


@athlete_required
@require_POST
def done(request, log_id, video_id):
    """The browser finished uploading: check the file is really there, then tell the coach."""
    log = _log(request, log_id)
    video = get_object_or_404(FormVideo, pk=video_id, session_log=log, uploaded_at__isnull=True)
    if videos.stored_size(video.key) != video.size:
        return JsonResponse({"error": "The upload didn't finish — try again."}, status=400)
    video.uploaded_at = timezone.now()
    video.save(update_fields=["uploaded_at"])
    alerts.video_uploaded(video)
    return _card(
        request,
        video.session_exercise,
        f"Video sent — {log.athlete.coach.user.get_short_name()} will review it",
        "good",
    )


@athlete_required
@require_POST
def note(request, log_id, video_id):
    log = _log(request, log_id)
    video = get_object_or_404(FormVideo, pk=video_id, session_log=log)
    video.note = " ".join(request.POST.get("note", "").split())[:300]
    video.save(update_fields=["note"])
    alerts.video_uploaded(video, reopen=False)  # keep the coach's feed text current
    return hx.toast(HttpResponse(status=204), "Note saved")


@athlete_required
@require_POST
def remove(request, log_id, video_id):
    log = _log(request, log_id)
    video = get_object_or_404(FormVideo, pk=video_id, session_log=log, reviewed_at__isnull=True)
    se = video.session_exercise
    videos.delete(video.key)
    alerts.video_removed(video)
    video.delete()
    return _card(request, se, "Video removed")


# ---------------------------------------------------------------- coach


class ReviewForm(forms.Form):
    feedback = forms.CharField(required=False, max_length=4000)


@coach_required
def review(request, pk, video_id):
    """GET: the video with a feedback box. POST: send the feedback and mark it reviewed."""
    from apps.messaging.models import Message, Thread

    athlete = coach_athlete(request, pk)
    video = get_object_or_404(FormVideo.objects.available(), pk=video_id, session_log__athlete=athlete)
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        feedback = form.cleaned_data["feedback"].strip()
        if feedback:
            thread = Thread.for_athlete(athlete)
            body = f"Form check — {video.exercise_name} ({video.session_log.date:%a %-d %b}): {feedback}"
            message = Message.objects.create(thread=thread, sender=request.user, body=body)
            alerts.message_sent(message)
        video.feedback, video.reviewed_at, video.reviewed_by = feedback, timezone.now(), request.user
        video.save(update_fields=["feedback", "reviewed_at", "reviewed_by"])
        alerts.video_reviewed(video)
        response = TemplateResponse(
            request, "coach/athlete/_video_note.html", {"video": video, "athlete": athlete}
        )
        name = athlete.user.get_short_name()
        hx.toast(response, f"Feedback sent to {name}" if feedback else "Marked reviewed", "good")
        return hx.trigger_after_swap(response, closeModal=True)
    return TemplateResponse(
        request,
        "coach/athlete/_video_modal.html",
        {"video": video, "athlete": athlete, "form": form, "src": videos.view_url(video.key)},
    )
