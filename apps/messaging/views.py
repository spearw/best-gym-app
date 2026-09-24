"""Coach–athlete messages: the coach's Messages tab on the athlete detail page and the
athlete's Coach tab. The thread polls every 20 seconds; opening it marks the other
side's messages read (and clears the coach's feed item)."""

from django import forms
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.access import athlete_required, coach_required
from apps.accounts.coach_views import _header_context, coach_athlete
from apps.dashboard import alerts

from .models import Message, Thread

SHOWN = 100  # most recent messages shown


class MessageForm(forms.Form):
    body = forms.CharField(max_length=4000)


def _thread_context(thread, viewer, send_url, poll_url, mobile=False):
    unread = thread.unread_for(viewer)
    if unread.exists():
        unread.update(read_at=timezone.now())
        if viewer == thread.coach.user:
            alerts.thread_read(thread)
    messages = list(thread.messages.select_related("sender").order_by("-sent_at", "-id")[:SHOWN])[::-1]
    return {
        "thread": thread,
        "thread_messages": messages,
        "viewer": viewer,
        "send_url": send_url,
        "poll_url": poll_url,
        "mobile": mobile,
    }


def _send(request, thread):
    form = MessageForm(request.POST)
    if form.is_valid() and form.cleaned_data["body"].strip():
        message = Message.objects.create(
            thread=thread, sender=request.user, body=form.cleaned_data["body"].strip()
        )
        alerts.message_sent(message)


# ---------------------------------------------------------------- coach


def _coach_urls(athlete):
    from django.urls import reverse

    return reverse("coach:message_send", args=[athlete.pk]), reverse(
        "coach:message_thread", args=[athlete.pk]
    )


def coach_tab(request, athlete):
    thread = Thread.for_athlete(athlete)
    context = {
        **_header_context(request, athlete),
        "tab": "messages",
        **_thread_context(thread, request.user, *_coach_urls(athlete)),
    }
    return TemplateResponse(request, "messaging/coach_tab.html", context)


@coach_required
def coach_thread(request, pk):
    athlete = coach_athlete(request, pk)
    thread = Thread.for_athlete(athlete)
    return TemplateResponse(
        request, "messaging/_thread.html", _thread_context(thread, request.user, *_coach_urls(athlete))
    )


@coach_required
@require_POST
def coach_send(request, pk):
    athlete = coach_athlete(request, pk)
    thread = Thread.for_athlete(athlete)
    _send(request, thread)
    return TemplateResponse(
        request, "messaging/_thread.html", _thread_context(thread, request.user, *_coach_urls(athlete))
    )


# ---------------------------------------------------------------- athlete


def _athlete_urls():
    from django.urls import reverse

    return reverse("app:message_send"), reverse("app:message_thread")


@athlete_required
def athlete_tab(request):
    thread = Thread.for_athlete(request.athlete)
    context = {
        "tab": "coach",
        "coach_name": request.athlete.coach.user.get_short_name(),
        **_thread_context(thread, request.user, *_athlete_urls(), mobile=True),
    }
    return TemplateResponse(request, "messaging/athlete_tab.html", context)


@athlete_required
def athlete_thread(request):
    thread = Thread.for_athlete(request.athlete)
    context = _thread_context(thread, request.user, *_athlete_urls(), mobile=True)
    return TemplateResponse(request, "messaging/_thread.html", context)


@athlete_required
@require_POST
def athlete_send(request):
    thread = Thread.for_athlete(request.athlete)
    _send(request, thread)
    context = _thread_context(thread, request.user, *_athlete_urls(), mobile=True)
    return TemplateResponse(request, "messaging/_thread.html", context)


def unread_for_athlete(user):
    athlete = getattr(user, "athlete_profile", None)
    if athlete is None:
        return 0
    return (
        Message.objects.filter(thread__athlete=athlete, thread__coach=athlete.coach, read_at__isnull=True)
        .exclude(sender=user)
        .count()
    )
