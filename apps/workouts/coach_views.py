"""The coach's Sessions tab: every logged session with the check-in, what was asked
for (from the snapshot taken when the session started) beside what was done, the
post-session RPE and comment, and any issue reported."""

import datetime

from django.template.response import TemplateResponse

from apps.programs.prescriptions import summary

from . import history, sessions
from .models import QuestionType

RANGES = [("4", "Last 4 weeks", 28), ("8", "Last 8 weeks", 56), ("all", "All time", None)]


def _asked(se, unit):
    p = sessions.prescribed(se)
    if p is None:
        return "not on the program"
    text = summary(p, unit, p.overrides)
    kg = sessions.target_kg(p, p.load_value)
    if kg and not p.overrides and p.load_basis == "percent":
        text += f" (≈ {sessions.plate_round(kg, unit)} {unit})"
    return text


def _exercise_line(se, unit, pr_ids):
    done = [s for s in se.sets.all() if s.done]
    entry = history.Entry(
        se.session_log.date, se.session_log_id, se.pk, se.exercise_id, se.exercise_name, done
    )
    e1rm = entry.best_e1rm
    return {
        "name": se.exercise_name,
        "deleted": se.exercise_id is None,
        "asked": _asked(se, unit),
        "did": history.sets_text(done, unit),
        "e1rm": history.e1rm_text(e1rm, unit) if e1rm else "",
        "pr": se.pk in pr_ids,
        "planned": sessions.planned_sets(se),
        "done_count": len(done),
    }


def _session_item(log, unit, pr_ids):
    exercises = [_exercise_line(se, unit, pr_ids) for se in log.exercises.all()]
    answers = list(log.answers.all())
    scale = next((a for a in answers if a.type == QuestionType.SCALE), None)
    issues = list(log.issues.all())
    rpe = log.session_rpe
    return {
        "log": log,
        "exercises": exercises,
        "answers": answers,
        "readiness": scale.value if scale else None,
        "issues": issues,
        "pr_day": any(e["pr"] for e in exercises),
        "rpe_class": "" if rpe is None else "hi" if rpe >= 9 else "mid" if rpe >= 7 else "lo",
        "status": "partial" if issues or not log.finished else "done",
    }


def sessions_tab(request, athlete, header_context):
    unit = request.coach.gym.units
    q = request.GET.get("q", "").strip()
    range_key = request.GET.get("range", "8")
    days = dict((k, d) for k, _label, d in RANGES).get(range_key, 56)
    logs = athlete.session_logs.select_related("week_type", "athlete__user").prefetch_related(
        "answers", "issues", "exercises__sets", "exercises__session_log"
    )
    if days:
        logs = logs.filter(date__gte=athlete.today() - datetime.timedelta(days=days))
    if q:
        logs = logs.filter(exercises__exercise_name__icontains=q).distinct()
    logs = logs.order_by("-date", "-started_at")
    pr_ids = history.pr_session_exercises(athlete)
    items = [_session_item(log, unit, pr_ids) for log in logs]
    today = athlete.today()
    for item in items:
        item["open"] = (today - item["log"].date).days < 3
    context = {
        **header_context,
        "tab": "sessions",
        "items": items,
        "q": q,
        "range_key": range_key if range_key in dict((k, d) for k, _l, d in RANGES) else "8",
        "ranges": RANGES,
    }
    if request.htmx and request.htmx.target == "sessLog":
        return TemplateResponse(request, "coach/athlete/_sessions_list.html", context)
    return TemplateResponse(request, "coach/athlete/sessions.html", context)
