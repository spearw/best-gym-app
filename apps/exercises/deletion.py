"""Permanently deleting an exercise, and saying exactly what that removes first.

Only archived exercises can be deleted. Everything that points at an exercise must
be counted in `deletion_impact` and cleared in `delete_exercise`. When a later phase
adds a model with a ForeignKey to Exercise (e.g. template slots), extend both functions
here and the tests in tests/unit/test_tracked_lifts_and_delete.py.

Logged training is never deleted: sessions that included the exercise keep its name
(SessionExercise.exercise_name) and every set, but lose the link, so trends, PRs and
"last done" stop counting it. Deleting is meant for typos and test entries.
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
    return {
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


@transaction.atomic
def delete_exercise(exercise):
    check_deletable(exercise)
    impact = deletion_impact(exercise)
    from apps.programs.models import Prescription
    from apps.workouts.models import SessionExercise

    SessionExercise.objects.filter(exercise=exercise).update(exercise=None)  # keeps exercise_name and sets
    MaxEntry.objects.filter(exercise=exercise).delete()
    Prescription.objects.filter(exercise=exercise).delete()
    Exercise.objects.filter(percent_of=exercise).update(percent_of=None)  # fall back to their own max
    TrackedLift.objects.filter(
        exercise=exercise
    ).delete()  # archived exercises aren't tracked; belt and braces
    exercise.delete()
    return impact
