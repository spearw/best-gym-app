"""Values derived from session logs, never stored (docs/BUILD_PLAN.md, "Derived values").

- e1RM per set = load × (1 + reps/30); an exercise's session e1RM is its best set.
- The "top set" of an exercise in a session is its heaviest done set (the mockup's "top").
- History counts finished sessions only, and done sets only.
- Day status: done when a finished log points at one of the day's sessions; missed when
  the date has passed in the athlete's zone and none does; today; upcoming; rest.
- Streak: consecutive scheduled days done, counted back from today (today itself only
  counts once it's done).
"""

import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from apps.accounts import units

from .models import SessionExercise, SessionLog, SetLog


def e1rm(load_kg, reps):
    if not load_kg or not reps:
        return None
    return (Decimal(load_kg) * (1 + Decimal(reps) / 30)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Entry:
    """One exercise in one finished session, as the history strip and PRs read it."""

    date: datetime.date
    log_id: int
    session_exercise_id: int
    exercise_id: int | None
    name: str
    sets: list = field(default_factory=list)  # done SetLogs, in order

    @property
    def top(self):
        """Heaviest done set (most reps breaks a tie); unloaded work: the most reps or time."""
        loaded = [s for s in self.sets if s.load_kg]
        if loaded:
            return max(loaded, key=lambda s: (s.load_kg, s.reps or 0))
        return max(self.sets, key=lambda s: (s.reps or 0, s.duration_seconds or 0), default=None)

    @property
    def best_e1rm(self):
        values = [v for v in (e1rm(s.load_kg, s.reps) for s in self.sets) if v]
        return max(values, default=None)


def set_text(s, unit):
    """'78 kg ×2', '×10', '10 min' or '30 s' for one set, in the viewer's unit."""
    if s is None:
        return ""
    parts = []
    if s.load_kg:
        parts.append(units.display(s.load_kg, unit))
    if s.reps:
        parts.append(f"×{s.reps}")
    elif s.duration_seconds:
        parts.append(duration_text(s.duration_seconds))
    return " ".join(parts)


def sets_text(sets, unit):
    """Done sets grouped like a prescription (sets×reps): '6×2 @ 64 kg, 1×1 @ 70 kg'."""
    groups = []
    for s in sets:
        key = (s.load_kg, s.reps, s.duration_seconds)
        if groups and groups[-1][0] == key:
            groups[-1][1] += 1
        else:
            groups.append([key, 1])
    parts = []
    for (load, reps, seconds), count in groups:
        dose = str(reps) if reps else duration_text(seconds) if seconds else "done"
        text = f"{count}×{dose}" if dose != "done" else f"{count} set{'s' if count > 1 else ''}"
        if load:
            text += f" @ {units.display(load, unit)}"
        parts.append(text)
    return ", ".join(parts)


def e1rm_text(kg, unit):
    """e1RM to the nearest whole kg or lb, as the mockup shows it."""
    return f"{units.from_kg(kg, unit).quantize(Decimal('1'), rounding=ROUND_HALF_UP)} {unit}"


def duration_text(seconds):
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    if seconds > 60:
        return f"{seconds // 60} min {seconds % 60} s"
    return f"{seconds} s"


def _entries(athlete, exercise_ids=None, exclude_log=None):
    """Every exercise the athlete did in a finished session, newest first."""
    sets = (
        SetLog.objects.filter(
            done=True,
            session_exercise__session_log__athlete=athlete,
            session_exercise__session_log__finished_at__isnull=False,
        )
        .select_related("session_exercise__session_log")
        .order_by(
            "-session_exercise__session_log__date", "-session_exercise__session_log__started_at", "set_number"
        )
    )
    if exercise_ids is not None:
        sets = sets.filter(session_exercise__exercise_id__in=exercise_ids)
    if exclude_log is not None:
        sets = sets.exclude(session_exercise__session_log=exclude_log)
    entries = {}
    for s in sets:
        se = s.session_exercise
        entry = entries.get(se.pk)
        if entry is None:
            entry = entries[se.pk] = Entry(
                se.session_log.date, se.session_log_id, se.pk, se.exercise_id, se.exercise_name
            )
        entry.sets.append(s)
    return list(entries.values())  # dicts keep insertion order: newest first


def exercise_history(athlete, exercise_ids=None, exclude_log=None, limit=10):
    """{exercise_id: [Entry, ...]} newest first, at most `limit` each."""
    history = {}
    for entry in _entries(athlete, exercise_ids, exclude_log):
        if entry.exercise_id is None:
            continue
        items = history.setdefault(entry.exercise_id, [])
        if len(items) < limit:
            items.append(entry)
    return history


def trend(entries):
    """'up', 'down' or 'flat' from the last two sessions' e1RM (or top load); None if too few."""
    if len(entries) < 2:
        return None
    a, b = (e.best_e1rm or (e.top.load_kg if e.top else None) for e in entries[:2])
    if not a or not b:
        return "flat"
    return "up" if a > b else "down" if a < b else "flat"


def ago(date, today):
    days = (today - date).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} wk ago"
    return f"{days // 30} mo ago"


def last_line(entry, unit, today):
    """'78 kg ×1 · 2 days ago' for the player and the library rail."""
    return f"{set_text(entry.top, unit)} · {ago(entry.date, today)}"


# ---------------------------------------------------------------- PRs


def lifetime_prs(athlete):
    """Per loaded exercise: heaviest set and best e1RM with their dates, most recent PR first."""
    best = {}
    for entry in reversed(_entries(athlete)):  # oldest first, so ties keep the first time
        if entry.exercise_id is None:
            continue
        top = entry.top
        if not top or not top.load_kg:
            continue
        pr = best.setdefault(
            entry.exercise_id,
            {"name": entry.name, "heaviest": None, "heaviest_date": None, "e1rm": None, "e1rm_date": None},
        )
        pr["name"] = entry.name
        if pr["heaviest"] is None or top.load_kg > pr["heaviest"].load_kg:
            pr["heaviest"], pr["heaviest_date"] = top, entry.date
        value = entry.best_e1rm
        if value and (pr["e1rm"] is None or value > pr["e1rm"]):
            pr["e1rm"], pr["e1rm_date"] = value, entry.date
    items = list(best.values())
    for pr in items:
        pr["date"] = max(d for d in (pr["heaviest_date"], pr["e1rm_date"]) if d)
    return sorted(items, key=lambda p: (p["date"], p["name"]), reverse=True)


def pr_session_exercises(athlete):
    """SessionExercise ids whose top set beat every earlier logged set of that exercise
    and the working max recorded before it. The first time doing a lift is not a PR
    unless it beats a recorded max."""
    maxes = {}
    for m in athlete.maxes.filter(set_log__isnull=True).order_by("date", "id"):
        maxes.setdefault(m.exercise_id, []).append(m)
    best, prs = {}, set()
    for entry in reversed(_entries(athlete)):
        top = entry.top
        if entry.exercise_id is None or not top or not top.load_kg:
            continue
        earlier = [m.kg for m in maxes.get(entry.exercise_id, []) if m.date <= entry.date]
        bar = max([*earlier, best.get(entry.exercise_id, Decimal(0))])
        if bar and top.load_kg > bar:
            prs.add(entry.session_exercise_id)
        best[entry.exercise_id] = max(best.get(entry.exercise_id, Decimal(0)), top.load_kg)
    return prs


# ---------------------------------------------------------------- days and streaks

DONE, MISSED, TODAY, UPCOMING, REST = "done", "missed", "today", "upcoming", "rest"


def day_status(day, today, finished_session_ids):
    """For a ProgramDay with its sessions prefetched."""
    sessions = list(day.sessions.all())
    if not sessions:
        return REST
    if any(s.pk in finished_session_ids for s in sessions):
        return DONE
    if day.date < today:
        return MISSED
    return TODAY if day.date == today else UPCOMING


def finished_session_ids(athlete):
    return set(
        SessionLog.objects.finished()
        .filter(athlete=athlete, program_session__isnull=False)
        .values_list("program_session_id", flat=True)
    )


def scheduled_days(athlete, until):
    """(date, done) for every day with a session in a published week of the athlete's
    active program, up to and including `until`, newest first."""
    from apps.programs.models import ProgramDay

    days = (
        ProgramDay.objects.filter(
            week__program__athlete=athlete,
            week__program__active=True,
            week__published=True,
            date__lte=until,
            sessions__isnull=False,
        )
        .distinct()
        .prefetch_related("sessions")
        .order_by("-date")
    )
    done_ids = finished_session_ids(athlete)
    return [(d.date, any(s.pk in done_ids for s in d.sessions.all())) for d in days]


def streak(athlete, today=None):
    today = today or athlete.today()
    count = 0
    for date, done in scheduled_days(athlete, today):
        if date == today and not done:
            continue  # today isn't missed yet
        if not done:
            break
        count += 1
    return count


def next_session_date(athlete, after):
    from apps.programs.models import ProgramDay

    day = (
        ProgramDay.objects.filter(
            week__program__athlete=athlete,
            week__program__active=True,
            week__published=True,
            date__gt=after,
            sessions__isnull=False,
        )
        .order_by("date")
        .first()
    )
    return day.date if day else None


def logged_exercises(log):
    return SessionExercise.objects.filter(session_log=log).prefetch_related("sets")
