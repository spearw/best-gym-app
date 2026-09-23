"""Settings › Tracked lifts: the gym-wide, ordered list of lifts whose maxes are
asked at onboarding and shown on the Metrics tab and athlete header."""

from django.db import transaction
from django.db.models import Max
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts.access import coach_required

from .models import MAX_TRACKED_LIFTS, Exercise, Measure, TrackedLift


def trackable(gym):
    """Exercises a gym could add: its own, active, rep-measured, not already tracked."""
    return (
        Exercise.objects.filter(gym=gym, archived=False, measure=Measure.REPS)
        .exclude(tracked_by__gym=gym)
        .order_by("name")
    )


def render_card(request, message=None, kind=""):
    gym = request.coach.gym
    response = TemplateResponse(
        request,
        "exercises/_tracked_lifts.html",
        {
            "tracked": TrackedLift.objects.filter(gym=gym).select_related("exercise__category"),
            "trackable": trackable(gym),
            "max_tracked": MAX_TRACKED_LIFTS,
        },
    )
    return hx.toast(response, message, kind) if message else response


@coach_required
def card(request):
    return render_card(request)


@coach_required
@require_POST
def add(request):
    gym = request.coach.gym
    with transaction.atomic():
        current = TrackedLift.objects.select_for_update().filter(gym=gym)
        if current.count() >= MAX_TRACKED_LIFTS:
            return render_card(request, f"Track up to {MAX_TRACKED_LIFTS} lifts", "bad")
        exercise = trackable(gym).filter(pk=request.POST.get("exercise")).first()
        if exercise is None:
            return render_card(request, "Pick a lift to track", "bad")
        next_order = (current.aggregate(m=Max("order"))["m"] or 0) + 1
        TrackedLift.objects.create(gym=gym, exercise=exercise, order=next_order)
    return render_card(
        request, f"Now tracking {exercise.name} — athletes are asked for it at onboarding", "good"
    )


@coach_required
@require_POST
def remove(request, pk):
    tracked = get_object_or_404(TrackedLift, pk=pk, gym=request.coach.gym)
    name = tracked.exercise.name
    tracked.delete()
    return render_card(
        request, f"Stopped tracking {name}. Maxes already recorded stay in each athlete's history."
    )


@coach_required
@require_POST
def move(request, pk, direction):
    gym = request.coach.gym
    with transaction.atomic():
        rows = list(TrackedLift.objects.select_for_update().filter(gym=gym))
        ids = [r.pk for r in rows]
        if pk not in ids or direction not in ("up", "down"):
            raise Http404
        i = ids.index(pk)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(rows):
            rows[i], rows[j] = rows[j], rows[i]
            for order, row in enumerate(rows):
                if row.order != order:
                    row.order = order
                    row.save(update_fields=["order"])
    return render_card(request)
