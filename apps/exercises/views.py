from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts.access import coach_required

from .deletion import CannotDelete, check_deletable, delete_exercise, deletion_impact
from .forms import ExerciseForm
from .models import Exercise, Tag, TrackedLift


def _filtered(request):
    gym = request.coach.gym
    q = request.GET.get("q", "").strip()
    tag_ids = {t for t in request.GET.getlist("tag") if t.isdigit()}
    tags = list(Tag.objects.filter(gym=gym, pk__in=tag_ids))
    show_archived = request.GET.get("archived") == "1"
    exercises = (
        Exercise.objects.filter(gym=gym, archived=show_archived)
        .select_related("percent_of", "category")
        .prefetch_related("tags")
    )
    if q:
        exercises = exercises.filter(
            Q(name__icontains=q)
            | Q(tags__name__icontains=q)
            | Q(cue__icontains=q)
            | Q(category__name__icontains=q)
        ).distinct()
    for tag in tags:
        exercises = exercises.filter(tags=tag)
    return exercises.order_by("category__order", "name"), {
        "q": q,
        "tags": tags,
        "tag_ids": {t.pk for t in tags},
        "show_archived": show_archived,
    }


@coach_required
def exercise_list(request):
    exercises, filters = _filtered(request)
    tracked_ids = set(TrackedLift.objects.filter(gym=request.coach.gym).values_list("exercise_id", flat=True))
    context = {
        "tracked_ids": tracked_ids,
        "panel": "programming",
        "ptab": "exercises",
        "title": "Programming",
        "exercises": exercises,
        "all_tags": Tag.objects.filter(gym=request.coach.gym),
        **filters,
    }
    # The search box and tag chips re-request this URL with HX-Target=exlibResults.
    if request.htmx and request.htmx.target == "exlibResults":
        return TemplateResponse(request, "exercises/_results.html", context)
    return TemplateResponse(request, "exercises/library.html", context)


def _exercise(request, pk):
    return get_object_or_404(Exercise, pk=pk, gym=request.coach.gym)


@coach_required
def exercise_form(request, pk=None):
    """GET: the new/edit modal. POST: save, close the modal and refresh the list."""
    instance = _exercise(request, pk) if pk else None
    form = ExerciseForm(request.POST or None, instance=instance, gym=request.coach.gym)
    if request.method == "POST":
        if form.is_valid():
            exercise = form.save()
            response = HttpResponse("")
            verb = "updated" if instance else "added to the library"
            return hx.trigger(
                response,
                toast={"message": f"“{exercise.name}” {verb}", "kind": "good"},
                exercisesChanged=True,
            )
        return TemplateResponse(request, "exercises/_modal.html", {"form": form, "exercise": instance})
    return TemplateResponse(request, "exercises/_modal.html", {"form": form, "exercise": instance})


@coach_required
@require_POST
def exercise_archive(request, pk):
    exercise = _exercise(request, pk)
    users = Exercise.objects.filter(percent_of=exercise, archived=False).count()
    was_tracked = TrackedLift.objects.filter(exercise=exercise).exists()
    with transaction.atomic():
        exercise.archived = True
        exercise.save(update_fields=["archived"])
        TrackedLift.objects.filter(exercise=exercise).delete()
    message = f"“{exercise.name}” archived"
    if was_tracked:
        message += " and removed from tracked lifts"
    if users:
        message += f" — {users} exercise{'s' if users != 1 else ''} still take percentages from it"
    return hx.trigger(HttpResponse(""), toast={"message": message}, exercisesChanged=True)


@coach_required
@require_POST
def exercise_restore(request, pk):
    exercise = _exercise(request, pk)
    exercise.archived = False
    exercise.save(update_fields=["archived"])
    return hx.trigger(
        HttpResponse(""),
        toast={"message": f"“{exercise.name}” restored", "kind": "good"},
        exercisesChanged=True,
    )


@coach_required
def exercise_delete(request, pk):
    """GET: the warning modal listing what will be removed. POST: delete for good."""
    exercise = _exercise(request, pk)
    try:
        check_deletable(exercise)
        problem = None
    except CannotDelete as err:
        problem = str(err)
    if request.method == "POST":
        if problem:
            return hx.toast(HttpResponse(""), problem, "bad")
        name = exercise.name
        impact = delete_exercise(exercise)
        message = f"“{name}” deleted"
        if impact["max_entries"]:
            n = impact["max_entries"]
            message += f" along with {n} max entr{'ies' if n != 1 else 'y'}"
        return hx.trigger(HttpResponse(""), toast={"message": message}, exercisesChanged=True)
    return TemplateResponse(
        request,
        "exercises/_delete_modal.html",
        {"exercise": exercise, "problem": problem, "impact": deletion_impact(exercise)},
    )
