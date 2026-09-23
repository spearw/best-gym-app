"""When a session beats a working max.

Only a real lift counts: the heaviest load done for at least one rep, above the latest
max of that same exercise (and logged on or after that max's date). An e1RM from a
triple shows in the PR list but never changes a max. Exercises with no max on file
never get one from a session; percentages worked from another lift's max
(Exercise.percent_of) don't move that lift's max either.

Each athlete has a setting (Athlete.max_updates): update the max automatically, or wait
for the coach, who sees the new best on the athlete's Metrics tab and either uses it
as the working max or keeps the current one.
"""

from dataclasses import dataclass

from django.db import transaction

from apps.accounts.models import MaxEntry, MaxUpdates, MeasurementSource

from .models import SetLog


@dataclass
class Candidate:
    set_log: SetLog
    current: MaxEntry

    @property
    def exercise(self):
        return self.current.exercise


def _best(sets):
    lifts = [s for s in sets if s.done and s.load_kg and (s.reps or 0) >= 1 and not s.max_dismissed]
    return max(lifts, key=lambda s: (s.load_kg, s.reps), default=None)


def _beats(set_log, current, date):
    return current is not None and set_log.load_kg > current.kg and date >= current.date


def session_candidates(log):
    """Sets in this session that beat a working max."""
    found = []
    maxes = log.athlete.current_maxes()
    for se in log.exercises.prefetch_related("sets"):
        if se.exercise_id is None:
            continue
        best = _best(se.sets.all())
        current = maxes.get(se.exercise_id)
        if best and _beats(best, current, log.date):
            found.append(Candidate(best, current))
    return found


@transaction.atomic
def apply(log):
    """Called when a session is finished or edited: redo the maxes it set automatically.
    A max the coach accepted from it stays."""
    MaxEntry.objects.filter(
        set_log__session_exercise__session_log=log, source=MeasurementSource.SESSION
    ).delete()
    if not log.finished or log.athlete.max_updates != MaxUpdates.AUTO:
        return []
    created = []
    for c in session_candidates(log):
        created.append(_use(log.athlete, c.set_log, MeasurementSource.SESSION))
    return created


def _use(athlete, set_log, source):
    se = set_log.session_exercise
    return MaxEntry.objects.create(
        athlete=athlete,
        exercise_id=se.exercise_id,
        date=se.session_log.date,
        kg=set_log.load_kg,
        reps=1,
        source=source,
        set_log=set_log,
    )


def pending(athlete):
    """For the coach to review: per exercise with a max, the best logged set that beats it."""
    maxes = athlete.current_maxes()
    if not maxes:
        return []
    sets = (
        SetLog.objects.filter(
            done=True,
            max_dismissed=False,
            reps__gte=1,
            load_kg__isnull=False,
            session_exercise__session_log__athlete=athlete,
            session_exercise__session_log__finished_at__isnull=False,
            session_exercise__exercise_id__in=maxes.keys(),
        )
        .select_related("session_exercise__session_log", "session_exercise__exercise")
        .order_by("-load_kg", "-reps")
    )
    found = {}
    for s in sets:
        se = s.session_exercise
        if se.exercise_id in found:
            continue
        if _beats(s, maxes[se.exercise_id], se.session_log.date):
            found[se.exercise_id] = Candidate(s, maxes[se.exercise_id])
    return sorted(found.values(), key=lambda c: c.exercise.name)


def pending_set(athlete, set_id):
    return next((c for c in pending(athlete) if c.set_log.pk == int(set_id)), None)


def accept(athlete, candidate):
    return _use(athlete, candidate.set_log, MeasurementSource.COACH)


def dismiss(athlete, candidate):
    """Keep the current max: every set now beating it for this exercise stops being offered."""
    current = candidate.current
    return SetLog.objects.filter(
        max_dismissed=False,
        load_kg__gt=current.kg,
        session_exercise__exercise_id=current.exercise_id,
        session_exercise__session_log__athlete=athlete,
        session_exercise__session_log__date__gte=current.date,
    ).update(max_dismissed=True)
