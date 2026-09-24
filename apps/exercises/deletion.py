"""Permanently deleting an exercise, and saying exactly what that removes first.

Only archived exercises can be deleted. Everything that points at an exercise must
be counted in `deletion_impact` and cleared in `delete_exercise`. When a later phase
adds a model with a ForeignKey to Exercise (e.g. template slots), extend both functions
here and the tests in tests/unit/test_tracked_lifts_and_delete.py.

Logged training is never deleted: sessions that included the exercise keep its name
(SessionExercise.exercise_name) and every set, but lose the link, so trends, PRs and
"last done" stop counting it. Deleting is meant for typos and test entries.

Template slots: a fixed slot for the exercise is removed; a tag slot that uses it as
its default switches to another exercise with all the slot's tags, or is removed if
none has them.

Those foreign keys should stay PROTECT, so anything missed here fails loudly instead
of silently cascading.
"""

from django.db import transaction

from apps.accounts.models import MaxEntry

from .models import Exercise, TrackedLift


class CannotDelete(Exception):
    pass


def check_deletable(exercise):
    if not exercise.archived:
        raise CannotDelete("Archive the exercise before deleting it.")


def deletion_impact(exercise):
    """What deleting this exercise would remove or change, for the warning."""
    from apps.programs.models import Prescription
    from apps.workouts.models import SessionExercise

    maxes = MaxEntry.objects.filter(exercise=exercise)
    prescriptions = Prescription.objects.filter(exercise=exercise)
    programmed_for = (
        prescriptions.order_by("session__day__week__program__athlete__user__name")
        .values_list("session__day__week__program__athlete__user__name", flat=True)
        .distinct()
    )
    athletes = maxes.order_by("athlete__user__name").values_list("athlete__user__name", flat=True).distinct()
    logged = SessionExercise.objects.filter(exercise=exercise)
    logged_by = (
        logged.order_by("session_log__athlete__user__name")
        .values_list("session_log__athlete__user__name", flat=True)
        .distinct()
    )
    replaced, removed = _template_slot_plan(exercise)
    return {
        "slots_removed": len(removed),
        "slots_redefaulted": len(replaced),
        "templates": sorted(
            {s.session.week.template.display_name for s in [*removed, *(s for s, _e in replaced)]}
        ),
        "logged": logged.count(),
        "logged_by": list(logged_by),
        "max_entries": maxes.count(),
        "athletes": list(athletes),
        "prescriptions": prescriptions.count(),
        "programmed_for": list(programmed_for),
        "dependents": list(
            Exercise.objects.filter(percent_of=exercise).order_by("name").values_list("name", flat=True)
        ),
    }


def _template_slot_plan(exercise):
    """([(tag slot, new default)], [slots to remove]) for the template slots using it."""
    from apps.library.models import TemplateSlot

    replaced, removed = [], []
    others = (
        Exercise.objects.filter(gym=exercise.gym, archived=False).exclude(pk=exercise.pk).order_by("name")
    )
    for slot in TemplateSlot.objects.filter(exercise=exercise).select_related("session__week__template"):
        tags = list(slot.tags.all()) if slot.is_tag else []
        candidates = others
        for tag in tags:
            candidates = candidates.filter(tags=tag)
        new_default = candidates.first() if tags else None
        if new_default:
            replaced.append((slot, new_default))
        else:
            removed.append(slot)
    return replaced, removed


@transaction.atomic
def delete_exercise(exercise):
    check_deletable(exercise)
    impact = deletion_impact(exercise)
    from apps.programs.models import Prescription
    from apps.workouts.models import SessionExercise

    SessionExercise.objects.filter(exercise=exercise).update(exercise=None)  # keeps exercise_name and sets
    replaced, removed = _template_slot_plan(exercise)
    for slot, new_default in replaced:
        slot.exercise = new_default
        slot.save(update_fields=["exercise"])
    for slot in removed:
        slot.delete()
    MaxEntry.objects.filter(exercise=exercise).delete()
    Prescription.objects.filter(exercise=exercise).delete()
    Exercise.objects.filter(percent_of=exercise).update(percent_of=None)  # fall back to their own max
    TrackedLift.objects.filter(
        exercise=exercise
    ).delete()  # archived exercises aren't tracked; belt and braces
    exercise.delete()
    return impact
