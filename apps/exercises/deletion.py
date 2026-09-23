"""Permanently deleting an exercise, and saying exactly what that removes first.

Only archived exercises can be deleted. Everything that points at an exercise must
be counted in `deletion_impact` and cleared in `delete_exercise`. When a later phase
adds a model with a ForeignKey to Exercise (prescriptions, template slots, session
logs), extend both functions here and the tests in tests/unit/test_exercises.py.
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
    maxes = MaxEntry.objects.filter(exercise=exercise)
    athletes = maxes.order_by("athlete__user__name").values_list("athlete__user__name", flat=True).distinct()
    return {
        "max_entries": maxes.count(),
        "athletes": list(athletes),
        "dependents": list(
            Exercise.objects.filter(percent_of=exercise).order_by("name").values_list("name", flat=True)
        ),
    }


@transaction.atomic
def delete_exercise(exercise):
    check_deletable(exercise)
    impact = deletion_impact(exercise)
    MaxEntry.objects.filter(exercise=exercise).delete()
    Exercise.objects.filter(percent_of=exercise).update(percent_of=None)  # fall back to their own max
    TrackedLift.objects.filter(
        exercise=exercise
    ).delete()  # archived exercises aren't tracked; belt and braces
    exercise.delete()
    return impact
