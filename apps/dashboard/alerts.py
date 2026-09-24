"""Everything that puts an item in (or takes it out of) the coach's attention feed.

Events call these as they happen: `message_sent`, `thread_read`, `issue_reported`,
`issue_resolved`, `sync_prs` (after a session is finished or edited, and after the
coach decides on a PR) and `max_updated`.

Conditions are checked by `sync_athlete` (dashboard load and the nightly job):
a program running out within PROGRAM_WARNING_DAYS (or no program at all), missing
metrics, and sessions missed in the last MISSED_LOOKBACK_DAYS. A condition's row is
deleted once it no longer holds, so it can fire again later; while it holds, a
dismissed row stays dismissed.
"""

import datetime

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Notification, NotificationKind

PROGRAM_WARNING_DAYS = 7
MISSED_LOOKBACK_DAYS = 7


def _tab(athlete, tab):
    return reverse("coach:athlete_tab", args=[athlete.pk, tab])


def notify(athlete, kind, key, text, link, reopen=True):
    """Add or update the coach's row. `reopen` brings a handled or dismissed row back."""
    recipient = athlete.coach.user
    now = timezone.now()
    row, created = Notification.objects.get_or_create(
        recipient=recipient,
        kind=kind,
        dedupe_key=key,
        defaults={"athlete": athlete, "text": text[:300], "link": link, "created_at": now},
    )
    if created:
        return row
    row.text, row.link, row.athlete = text[:300], link, athlete
    if reopen:
        row.created_at, row.read_at, row.cleared_at = now, None, None
    row.save()
    return row


def handled(athlete, kind, key=None):
    """The coach dealt with it: gone from the feed (kept, so it doesn't fire again)."""
    rows = Notification.objects.filter(
        recipient=athlete.coach.user, athlete=athlete, kind=kind, cleared_at__isnull=True
    )
    if key is not None:
        rows = rows.filter(dedupe_key=key)
    now = timezone.now()
    return rows.update(cleared_at=now, read_at=now)


def _remove(athlete, kind, keep_keys=()):
    """A condition no longer holds: delete its rows so it can fire again later."""
    Notification.objects.filter(recipient=athlete.coach.user, athlete=athlete, kind=kind).exclude(
        dedupe_key__in=list(keep_keys)
    ).delete()


# ---------------------------------------------------------------- events


def message_sent(message):
    thread = message.thread
    athlete = thread.athlete
    if message.sender_id == athlete.user_id:
        body = " ".join(message.body.split())
        text = f"“{body[:120]}{'…' if len(body) > 120 else ''}”"
        notify(athlete, NotificationKind.MESSAGE, f"thread:{thread.pk}", text, _tab(athlete, "messages"))
    else:
        handled(athlete, NotificationKind.MESSAGE, f"thread:{thread.pk}")  # the coach replied


def thread_read(thread):
    handled(thread.athlete, NotificationKind.MESSAGE, f"thread:{thread.pk}")


def issue_reported(issue):
    text = issue.get_kind_display() + (f" — “{issue.text[:100]}”" if issue.text else "")
    notify(issue.athlete, NotificationKind.ISSUE, f"issue:{issue.pk}", text, _tab(issue.athlete, "sessions"))


def issue_resolved(issue):
    handled(issue.athlete, NotificationKind.ISSUE, f"issue:{issue.pk}")


def sync_prs(athlete):
    """One row per exercise with a session PR waiting for the coach; decided ones leave."""
    from apps.accounts import units
    from apps.workouts import prs

    unit = athlete.gym.units
    keys = []
    for c in prs.pending(athlete):
        key = f"pr:{c.exercise.pk}"
        keys.append(key)
        text = (
            f"{c.exercise.name} {units.display(c.set_log.load_kg, unit)} × {c.set_log.reps} — above the "
            f"{units.display(c.current.kg, unit)} working max. Use it, or keep the max?"
        )
        existing = Notification.objects.filter(
            recipient=athlete.coach.user, kind=NotificationKind.PR, dedupe_key=key
        ).first()
        notify(
            athlete,
            NotificationKind.PR,
            key,
            text,
            _tab(athlete, "metrics"),
            reopen=existing is None or existing.text != text,
        )
    stale = Notification.objects.filter(
        recipient=athlete.coach.user,
        athlete=athlete,
        kind=NotificationKind.PR,
        dedupe_key__startswith="pr:",
        cleared_at__isnull=True,
    ).exclude(dedupe_key__in=keys)
    now = timezone.now()
    stale.update(cleared_at=now, read_at=now)


def max_updated(entry):
    """A session PR that updated a max automatically: for the coach's information."""
    from apps.accounts import units

    athlete = entry.athlete
    text = (
        f"{entry.exercise.name} max updated to {units.display(entry.kg, athlete.gym.units)} from a session PR"
    )
    notify(athlete, NotificationKind.PR, f"auto:{entry.pk}", text, _tab(athlete, "metrics"))


# ---------------------------------------------------------------- conditions


def program_end_date(athlete):
    """The last day with a session in the athlete's active program (None: nothing planned)."""
    from apps.programs.models import ProgramDay

    program = athlete.programs.active().first()
    if program is None:
        return None, None
    day = ProgramDay.objects.filter(week__program=program, sessions__isnull=False).order_by("-date").first()
    return program, day.date if day else None


def _sync_program(athlete, today):
    program, last = program_end_date(athlete)
    kind = NotificationKind.PROGRAM_ENDING
    link = _tab(athlete, "program")
    if program is None:
        key, text = "none", "No program yet — build one or apply a template"
    elif last is None:
        key, text = f"program:{program.pk}", f"“{program.name}” has no sessions yet"
    elif last < today:
        key, text = (
            f"program:{program.pk}",
            f"“{program.name}” ended {last:%a %-d %b} — nothing scheduled after",
        )
    elif (last - today).days < PROGRAM_WARNING_DAYS:
        days = (last - today).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"{last:%A} ({days} days)"
        key, text = f"program:{program.pk}", f"“{program.name}” runs out {when} — nothing scheduled after"
    else:
        _remove(athlete, kind)
        return
    _remove(athlete, kind, keep_keys=[key])
    notify(athlete, kind, key, text, link, reopen=False)


def _sync_metrics(athlete):
    from apps.accounts.metrics import metric_specs, missing_metrics

    specs = {m.key: m.label for m in metric_specs(athlete.gym)}
    missing = [specs[k] for k in missing_metrics(athlete)]
    kind = NotificationKind.METRICS_MISSING
    if not missing:
        _remove(athlete, kind)
        return
    notify(athlete, kind, "metrics", "Missing: " + ", ".join(missing), _tab(athlete, "metrics"), reopen=False)


def _sync_missed(athlete, today):
    from apps.programs.models import ProgramDay
    from apps.workouts.history import finished_session_ids

    done = finished_session_ids(athlete)
    days = (
        ProgramDay.objects.filter(
            week__program__athlete=athlete,
            week__program__active=True,
            week__published=True,
            sessions__isnull=False,
            date__lt=today,
            date__gte=today - datetime.timedelta(days=MISSED_LOOKBACK_DAYS),
        )
        .distinct()
        .prefetch_related("sessions__prescriptions__exercise")
    )
    kind = NotificationKind.MISSED
    for day in days:
        key = f"day:{day.pk}"
        sessions = list(day.sessions.all())
        if any(s.pk in done for s in sessions):
            _remove_key(athlete, kind, key)
            continue
        names = [rx.exercise.name for s in sessions for rx in s.prescriptions.all()]
        what = " + ".join(names[:2]) + (f" + {len(names) - 2} more" if len(names) > 2 else "")
        text = f"Missed {day.date:%a %-d %b}" + (f" — {what}" if what else "")
        notify(athlete, kind, key, text, _tab(athlete, "program") + f"?week={day.week_id}", reopen=False)
    # Days logged afterwards (or no longer in the program) leave the feed.
    for row in Notification.objects.filter(recipient=athlete.coach.user, athlete=athlete, kind=kind):
        day_id = row.dedupe_key.removeprefix("day:")
        if not day_id.isdigit():
            continue
        day = ProgramDay.objects.filter(pk=day_id).prefetch_related("sessions").first()
        if day is None or any(s.pk in done for s in day.sessions.all()):
            row.delete()


def _remove_key(athlete, kind, key):
    Notification.objects.filter(
        recipient=athlete.coach.user, athlete=athlete, kind=kind, dedupe_key=key
    ).delete()


@transaction.atomic
def sync_athlete(athlete, today=None):
    """Bring the condition-based rows (and waiting PRs) up to date for one athlete."""
    athlete_today = athlete.today()
    _sync_program(athlete, today or athlete_today)
    _sync_metrics(athlete)
    _sync_missed(athlete, athlete_today)
    sync_prs(athlete)


def sync_coach(coach):
    for athlete in coach.athletes.filter(archived_at__isnull=True).select_related(
        "user", "gym", "coach__user"
    ):
        sync_athlete(athlete)


def feed(coach):
    """The coach's feed: newest first, for their current athletes."""
    return (
        Notification.objects.in_feed()
        .filter(recipient=coach.user, athlete__coach=coach, athlete__archived_at__isnull=True)
        .select_related("athlete__user")
    )


def unread_count(user):
    coach = getattr(user, "coach_profile", None)
    if coach is None:
        return 0
    return feed(coach).filter(read_at__isnull=True).count()
