"""The check-in question builder. One set of endpoints serves two owners:
the gym's defaults (/coach/questions/…) and one athlete's own copy
(/coach/athletes/<pk>/questions/…). Every endpoint re-renders the builder."""

from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts.access import coach_required
from apps.accounts.coach_views import coach_athlete

from .models import CheckinQuestion, QuestionType, copy_defaults_to

NEW_QUESTION = {
    QuestionType.SCALE: {"text": "New 1–10 question", "low_label": "low", "high_label": "high"},
    QuestionType.CHOICE: {"text": "New multiple-choice question", "options": ["Option A", "Option B"]},
}
MAX_OPTIONS = 12


class Scope:
    def __init__(self, request, athlete_pk=None):
        self.request = request
        if athlete_pk is None:
            self.athlete = None
            self.gym = request.coach.gym
            self.questions = CheckinQuestion.objects.gym_defaults(self.gym)
            self.create_kwargs = {"gym": self.gym}
            self.prefix = reverse("coach:questions")
            self.builder_id = "defQBuilder"
            self.saved_message = (
                "Defaults updated — new athletes get these; push them to update existing athletes"
            )
        else:
            self.athlete = coach_athlete(request, athlete_pk)
            self.gym = self.athlete.gym
            self.questions = CheckinQuestion.objects.for_athlete(self.athlete)
            self.create_kwargs = {"athlete": self.athlete}
            self.prefix = reverse("coach:athlete_questions", args=[self.athlete.pk])
            first = self.athlete.user.get_short_name()
            self.saved_message = f"Updated — live from {first}'s next session"
            self.builder_id = "qBuilder"

    def question(self, qid):
        return get_object_or_404(self.questions.filter(archived=False), pk=qid)

    def render(self, message=None, kind=""):
        response = TemplateResponse(
            self.request,
            "workouts/_question_builder.html",
            {
                "questions": self.questions.active(),
                "builder_prefix": self.prefix,
                "builder_id": self.builder_id,
                "athlete": self.athlete,
            },
        )
        return hx.toast(response, message, kind) if message else response


def _scope(view):
    @coach_required
    def wrapped(request, *args, athlete_pk=None, **kwargs):
        return view(request, Scope(request, athlete_pk), *args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


@_scope
def builder(request, scope):
    return scope.render()


@require_POST
@_scope
def add(request, scope, qtype):
    if qtype not in QuestionType.values:
        raise Http404
    next_order = (scope.questions.filter(archived=False).aggregate(m=Max("order"))["m"] or 0) + 1
    CheckinQuestion.objects.create(type=qtype, order=next_order, **NEW_QUESTION[qtype], **scope.create_kwargs)
    return scope.render("Question added — edit its wording below")


@require_POST
@_scope
def update(request, scope, qid):
    q = scope.question(qid)
    text = " ".join(request.POST.get("text", q.text).split())[:200]
    if not text:
        # Put the old wording back on screen.
        return hx.retarget(
            scope.render("A question needs some wording", "bad"), f"#{scope.builder_id}", "outerHTML"
        )
    q.text = text
    if q.type == QuestionType.SCALE:
        q.low_label = request.POST.get("low_label", q.low_label).strip()[:60]
        q.high_label = request.POST.get("high_label", q.high_label).strip()[:60]
    q.save()
    # The edited text is already on screen, so nothing is redrawn. Redrawing here would
    # drop any click (move, delete) queued behind this save.
    return hx.toast(HttpResponse(""), scope.saved_message)


@require_POST
@_scope
def archive(request, scope, qid):
    q = scope.question(qid)
    q.archived = True
    q.save(update_fields=["archived"])
    return scope.render("Question removed")


@require_POST
@_scope
def move(request, scope, qid, direction):
    with transaction.atomic():
        active = list(scope.questions.active().select_for_update())
        ids = [q.pk for q in active]
        try:
            i = ids.index(int(qid))
        except ValueError as err:
            raise Http404 from err
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(active):
            active[i], active[j] = active[j], active[i]
            for order, q in enumerate(active):
                if q.order != order:
                    q.order = order
                    q.save(update_fields=["order"])
    return scope.render()


@require_POST
@_scope
def add_option(request, scope, qid):
    q = scope.question(qid)
    option = " ".join(request.POST.get("option", "").split())[:80]
    if q.type != QuestionType.CHOICE or not option:
        return scope.render("Type the option first", "bad" if q.type == QuestionType.CHOICE else "")
    if option in q.options:
        return scope.render("That option is already there")
    if len(q.options) >= MAX_OPTIONS:
        return scope.render(f"Keep it to {MAX_OPTIONS} options", "bad")
    q.options = [*q.options, option]
    q.save(update_fields=["options"])
    return scope.render(scope.saved_message)


@require_POST
@_scope
def remove_option(request, scope, qid, index):
    q = scope.question(qid)
    if q.type != QuestionType.CHOICE or not 0 <= index < len(q.options):
        raise Http404
    if len(q.options) <= 2:
        return scope.render("A multiple-choice question needs at least two options", "bad")
    q.options = [o for i, o in enumerate(q.options) if i != index]
    q.save(update_fields=["options"])
    return scope.render(scope.saved_message)


@require_POST
@_scope
def reset_to_defaults(request, scope):
    if scope.athlete is None:
        raise Http404
    copy_defaults_to(scope.athlete)
    return scope.render("Reset to the default questions", "good")


@require_POST
@_scope
def push_defaults(request, scope):
    if scope.athlete is not None:
        raise Http404
    athletes = list(request.coach.athletes.filter(archived_at__isnull=True))
    with transaction.atomic():
        for athlete in athletes:
            copy_defaults_to(athlete)
    count = len(athletes)
    return scope.render(
        f"Default questions pushed to your {count} athlete{'s' if count != 1 else ''}", "good"
    )


@coach_required
def defaults_page(request):
    scope = Scope(request)
    return TemplateResponse(
        request,
        "workouts/questions_page.html",
        {
            "panel": "programming",
            "ptab": "questions",
            "title": "Programming",
            "questions": scope.questions.active(),
            "builder_prefix": scope.prefix,
            "builder_id": scope.builder_id,
            "athlete_count": request.coach.athletes.filter(archived_at__isnull=True).count(),
        },
    )
