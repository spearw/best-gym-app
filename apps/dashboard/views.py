"""The coach dashboard: KPIs, the roster table, the "Needs your attention" feed,
sessions today and recent sessions. The feed polls every 20 seconds; loading the
dashboard (and the nightly job) first brings the condition-based alerts up to date.

"Today" and "this week" on the dashboard use the gym's time zone and week start.
"""

import datetime
import zoneinfo

from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts.access import coach_required
from apps.accounts.metrics import missing_metrics
from apps.workouts import history
from apps.workouts.models import SessionLog

from . import alerts
from .models import Notification, NotificationKind

SORTS = [
    ("attention", "Needs attention first"),
    ("name", "Name A–Z"),
    ("compliance", "Compliance low→high"),
    ("competition", "Next competition"),
]
FEED_ICONS = {
    NotificationKind.ISSUE: "alert",
    NotificationKind.MESSAGE: "msg",
    NotificationKind.PR: "trophy",
    NotificationKind.PROGRAM_ENDING: "cal",
    NotificationKind.METRICS_MISSING: "user",
    NotificationKind.MISSED: "cal",
    NotificationKind.VIDEO: "video",
}
FEED_CLASS = {
    NotificationKind.ISSUE: "issue",
    NotificationKind.MESSAGE: "msg",
    NotificationKind.PROGRAM_ENDING: "prog",
    NotificationKind.PR: "pr",
    NotificationKind.METRICS_MISSING: "metrics",
    NotificationKind.MISSED: "missed",
}


def _athletes(coach):
    return list(coach.athletes.filter(archived_at__isnull=True).select_related("user", "gym", "coach__user"))


def _pct(done, scheduled):
    return round(done / scheduled * 100) if scheduled else None


def _current_week(athlete, today):
    program = athlete.programs.active().first()
    if program is None:
        return None
    return (
        program.weeks.filter(start_date__lte=today, start_date__gt=today - datetime.timedelta(days=7))
        .select_related("week_type")
        .first()
    )


def _roster_rows(coach, athletes, feed_rows):
    by_athlete = {}
    for row in feed_rows:
        if row.read_at is None:
            by_athlete.setdefault(row.athlete_id, []).append(row)
    rows = []
    for a in athletes:
        today = a.today()
        done, scheduled = history.compliance(a, today)
        last = a.session_logs.finished().prefetch_related("answers").order_by("-date", "-finished_at").first()
        readiness = None
        if last:
            scale = next((x for x in last.answers.all() if x.type == "scale"), None)
            readiness = scale.value if scale else None
        pct = _pct(done, scheduled)
        rows.append(
            {
                "athlete": a,
                "week": _current_week(a, today),
                "compliance": pct,
                "ring": "var(--good)"
                if pct is None or pct >= 85
                else "var(--warn)"
                if pct >= 70
                else "var(--bad)",
                "last": last,
                "readiness": readiness,
                "alerts": [
                    {"row": r, "icon": FEED_ICONS.get(r.kind, "bell"), "cls": FEED_CLASS.get(r.kind, "prog")}
                    for r in by_athlete.get(a.pk, [])
                ],
            }
        )
    return rows


def _sorted(rows, sort):
    if sort == "name":
        return sorted(rows, key=lambda r: (r["athlete"].user.name or r["athlete"].user.email).lower())
    if sort == "compliance":
        return sorted(rows, key=lambda r: (r["compliance"] is None, r["compliance"] or 0))
    if sort == "competition":
        far = datetime.date.max
        return sorted(rows, key=lambda r: r["athlete"].competition_date or far)
    return sorted(rows, key=lambda r: (-len(r["alerts"]), (r["athlete"].user.name or "").lower()))


def _kpis(coach, athletes):
    gym = coach.gym
    today = gym.today()
    month_start = today.replace(day=1)
    joined = sum(1 for a in athletes if timezone.localdate(a.joined_at, gym_zone(gym)) >= month_start)
    done = scheduled = prev_done = prev_scheduled = 0
    need = 0
    for a in athletes:
        d, s = history.compliance(a, a.today())
        pd, ps = history.compliance(a, a.today(), end=a.today() - datetime.timedelta(days=7))
        done, scheduled, prev_done, prev_scheduled = (
            done + d,
            scheduled + s,
            prev_done + pd,
            prev_scheduled + ps,
        )
        program, last = alerts.program_end_date(a)
        if program is None or last is None or (last - a.today()).days < alerts.PROGRAM_WARNING_DAYS:
            need += 1
    week_start = gym.week_start_for(today)
    days_in = (today - week_start).days
    logs = SessionLog.objects.finished().filter(athlete__in=athletes)
    this_week = logs.filter(date__gte=week_start, date__lte=today).count()
    last_week = logs.filter(
        date__gte=week_start - datetime.timedelta(days=7),
        date__lte=week_start - datetime.timedelta(days=7 - days_in),
    ).count()
    pct, prev = _pct(done, scheduled), _pct(prev_done, prev_scheduled)
    compliance_delta = pct - prev if pct is not None and prev is not None else 0
    sessions_delta = this_week - last_week
    return {
        "active": len(athletes),
        "joined": joined,
        "compliance": pct,
        "compliance_change": abs(compliance_delta),
        "compliance_dir": "up" if compliance_delta > 0 else "down",
        "sessions": this_week,
        "sessions_change": abs(sessions_delta),
        "sessions_dir": "up" if sessions_delta > 0 else "down",
        "need_programming": need,
    }


def gym_zone(gym):
    return zoneinfo.ZoneInfo(gym.timezone)


def _today_list(athletes, today):
    from apps.programs.models import ProgramDay

    done_ids = set(
        SessionLog.objects.finished()
        .filter(athlete__in=athletes, program_session__isnull=False)
        .values_list("program_session_id", flat=True)
    )
    days = {
        d.week.program.athlete_id: d
        for d in ProgramDay.objects.filter(
            week__program__athlete__in=athletes, week__program__active=True, week__published=True, date=today
        )
        .select_related("week__program")
        .prefetch_related("sessions__prescriptions")
    }
    items = []
    for a in athletes:
        day = days.get(a.pk)
        sessions = list(day.sessions.all()) if day else []
        count = sum(len(s.prescriptions.all()) for s in sessions)
        items.append({"athlete": a, "count": count, "done": any(s.pk in done_ids for s in sessions)})
    return items


def feed_context(request):
    rows = list(alerts.feed(request.coach))
    for r in rows:
        r.icon, r.cls = FEED_ICONS.get(r.kind, "bell"), FEED_CLASS.get(r.kind, "prog")
        r.href = alerts.link_for(r)
    return {
        "feed": rows,
        "unread": sum(1 for r in rows if r.read_at is None),
        "has_read": any(r.read_at for r in rows),
    }


@coach_required
def dashboard(request):
    coach = request.coach
    alerts.sync_coach(coach)
    athletes = _athletes(coach)
    sort = request.GET.get("sort", "attention")
    feed = feed_context(request)
    rows = _sorted(_roster_rows(coach, athletes, feed["feed"]), sort)
    context = {"panel": "dashboard", "title": "Dashboard", "rows": rows, "sort": sort, "sorts": SORTS}
    if request.htmx and request.htmx.target == "rosterBody":
        return TemplateResponse(request, "coach/_roster_rows.html", context)
    today = coach.gym.today()
    recent = (
        SessionLog.objects.finished()
        .filter(athlete__in=athletes, date__gte=today - datetime.timedelta(days=7))
        .select_related("athlete__user")
        .prefetch_related("issues")
        .order_by("-date", "-finished_at")[:8]
    )
    context.update(
        {
            **feed,
            "kpis": _kpis(coach, athletes),
            "today": today,
            "today_list": _today_list(athletes, today),
            "recent": recent,
            "missing_count": sum(1 for a in athletes if missing_metrics(a)),
        }
    )
    return TemplateResponse(request, "coach/dashboard.html", context)


def _feed_response(request, message=None):
    response = TemplateResponse(request, "coach/_feed.html", feed_context(request))
    return hx.toast(response, message) if message else response


@coach_required
def feed(request):
    """Polled every 20 seconds; also redraws the sidebar count out of band."""
    return _feed_response(request)


@coach_required
@require_POST
def dismiss(request, pk):
    row = get_object_or_404(Notification, pk=pk, recipient=request.user)
    row.read_at = row.read_at or timezone.now()
    row.save(update_fields=["read_at"])
    return _feed_response(request)


@coach_required
@require_POST
def clear_read(request):
    n = alerts.feed(request.coach).filter(read_at__isnull=False).update(cleared_at=timezone.now())
    return _feed_response(
        request, f"Cleared {n} read item{'s' if n != 1 else ''}" if n else "Nothing read to clear"
    )


@coach_required
@require_POST
def resolve_issue(request, pk, issue_id):
    from apps.accounts.coach_views import coach_athlete
    from apps.workouts.models import IssueReport

    athlete = coach_athlete(request, pk)
    issue = get_object_or_404(IssueReport, pk=issue_id, athlete=athlete)
    if issue.resolved_at is None:
        issue.resolved_at = timezone.now()
        issue.save(update_fields=["resolved_at"])
        alerts.issue_resolved(issue)
    response = TemplateResponse(
        request, "coach/athlete/_issue_note.html", {"issue": issue, "athlete": athlete}
    )
    return hx.toast(response, "Issue marked resolved", "good")
