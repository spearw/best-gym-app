"""The athlete app: week, check-in, session player, post-session, done, progress, profile.

Every lookup goes through request.athlete. A session log is found with _log(), which
404s for anyone else's. Screens are plain pages (boosted links and forms swap
#app-body); only set rows save in the background, one request per set.
"""

import datetime

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts import units
from apps.accounts.access import athlete_required
from apps.accounts.metrics import current_metrics, metric_specs, missing_metrics
from apps.exercises.models import Measure
from apps.programs.models import LoadBasis, ProgramSession
from apps.programs.prescriptions import load_text, summary

from . import history, sessions
from .forms import RIR_CHOICES, FinishForm, IssueForm, SetForm
from .models import EDIT_WINDOW, OTHER_OPTION, CheckinAnswer, CheckinQuestion, QuestionType, SessionLog


def _log(request, log_id):
    return get_object_or_404(
        SessionLog.objects.select_related("program_session__day__week", "week_type"),
        pk=log_id,
        athlete=request.athlete,
    )


def _coach_first_name(athlete):
    return athlete.coach.user.get_short_name()


# ---------------------------------------------------------------- home / week


def _published_weeks(program):
    return list(program.weeks.filter(published=True).select_related("week_type")) if program else []


def _pick_week(weeks, today, wanted):
    if not weeks:
        return None
    if wanted:
        for w in weeks:
            if w.start_date <= wanted <= w.end_date:
                return w
    for w in weeks:
        if w.start_date <= today <= w.end_date:
            return w
    # Before the first published week, show it; after the last, show the last.
    return weeks[0] if today < weeks[0].start_date else weeks[-1]


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _session_card(athlete, session, log, day_date, today, unit):
    rxs = list(session.prescriptions.all())
    card = {
        "session": session,
        "log": log,
        "items": [
            {"name": rx.exercise.name, "dose": summary(rx, unit, list(rx.set_overrides.all()), custom=False)}
            for rx in rxs
        ],
        "count": len(rxs),
    }
    if log and log.finished:
        card["state"] = "done"
        card["editable"] = log.editable()
    elif log:
        card["state"] = "paused"
    elif day_date == today:
        card["state"] = "start"
    elif day_date < today:
        card["state"] = "backfill"
    else:
        card["state"] = "locked"
    return card


@athlete_required
def home(request):
    athlete = request.athlete
    today = athlete.today()
    unit = athlete.units
    program = athlete.programs.active().first()
    weeks = _published_weeks(program)
    week = _pick_week(weeks, today, _parse_date(request.GET.get("week")))
    context = {
        "tab": "week",
        "program": program,
        "week": week,
        "today": today,
        "coach_name": _coach_first_name(athlete),
    }
    paused = list(athlete.session_logs.unfinished().order_by("-started_at"))
    if week is None:
        context["paused"] = paused
        return TemplateResponse(request, "app/home.html", context)

    days = list(
        week.days.prefetch_related(
            "sessions__prescriptions__exercise", "sessions__prescriptions__set_overrides", "sessions__logs"
        )
    )
    done_ids = history.finished_session_ids(athlete)
    selected_date = _parse_date(request.GET.get("day"))
    if not selected_date or not week.start_date <= selected_date <= week.end_date:
        selected_date = today if week.start_date <= today <= week.end_date else week.start_date
    strip = []
    selected = None
    for day in days:
        status = history.day_status(day, today, done_ids)
        sessions_ = list(day.sessions.all())
        entry = {
            "day": day,
            "status": status,
            "count": sum(len(s.prescriptions.all()) for s in sessions_),
            "is_today": day.date == today,
            "selected": day.date == selected_date,
        }
        strip.append(entry)
        if entry["selected"]:
            selected = entry
            entry["cards"] = [
                _session_card(athlete, s, next(iter(s.logs.all()), None), day.date, today, unit)
                for s in sessions_
            ]
    index = weeks.index(week)
    week_number = week.order + 1
    context.update(
        {
            "strip": strip,
            "selected": selected,
            "week_number": week_number,
            "prev_week": weeks[index - 1] if index > 0 else None,
            "next_week": weeks[index + 1] if index + 1 < len(weeks) else None,
            "paused": [p for p in paused if p.date != selected_date],
        }
    )
    return TemplateResponse(request, "app/home.html", context)


@athlete_required
@require_POST
def start(request, session_id):
    """Start (or resume) a planned session: today's, or a missed one filled in afterwards."""
    athlete = request.athlete
    session = get_object_or_404(
        ProgramSession.objects.select_related("day__week__week_type"),
        pk=session_id,
        day__week__program__athlete=athlete,
        day__week__published=True,
    )
    if session.day.date > athlete.today():
        messages.error(request, f"This session unlocks on {session.day.date:%A}.")
        return redirect(f"{reverse('app:home')}?day={session.day.date.isoformat()}")
    log = sessions.start(athlete, session)
    return redirect(_resume_url(log))


@athlete_required
def resume(request, log_id):
    return redirect(_resume_url(_log(request, log_id)))


def _questions(athlete):
    return list(CheckinQuestion.objects.for_athlete(athlete).active())


def _resume_url(log):
    """Where to pick a session up: the next unanswered check-in question, else the first
    exercise that still has sets to do."""
    if not log.finished and not log.checkin_skipped:
        answered = set(log.answers.values_list("question_id", flat=True))
        questions = _questions(log.athlete)
        if questions and not log.exercises.filter(sets__isnull=False).exists():
            for n, q in enumerate(questions, start=1):
                if q.pk not in answered:
                    return reverse("app:checkin", args=[log.pk, n])
            return reverse("app:checkin_summary", args=[log.pk])
    exercises = list(log.exercises.prefetch_related("sets"))
    for n, se in enumerate(exercises, start=1):
        done = sum(1 for s in se.sets.all() if s.done)
        if done < max(sessions.planned_sets(se), 1):
            return reverse("app:player", args=[log.pk, n])
    if log.finished and exercises:
        return reverse("app:player", args=[log.pk, 1])
    return reverse("app:finish", args=[log.pk])


# ---------------------------------------------------------------- check-in


def _flow(tabless_context):
    return {"hide_tabs": True, "tab": None, **tabless_context}


@athlete_required
def checkin(request, log_id, n):
    log = _log(request, log_id)
    if log.finished:
        return redirect("app:player", log.pk, 1)
    questions = _questions(request.athlete)
    if not 1 <= n <= len(questions):
        return redirect("app:checkin_summary", log.pk)
    question = questions[n - 1]
    answer = log.answers.filter(question=question).first()
    error = ""
    if request.method == "POST":
        value = request.POST.get("value", "").strip()
        other = request.POST.get("other_text", "").strip()
        valid = (
            value in {str(i) for i in range(1, 11)}
            if question.type == QuestionType.SCALE
            else value in [*question.options, OTHER_OPTION]
        )
        if valid:
            CheckinAnswer.objects.update_or_create(
                session_log=log,
                question=question,
                defaults={
                    "order": n - 1,
                    "question_text": question.text,
                    "type": question.type,
                    "value": value,
                    "other_text": other if value == OTHER_OPTION else "",
                },
            )
            if n < len(questions):
                return redirect("app:checkin", log.pk, n + 1)
            return redirect("app:checkin_summary", log.pk)
        error = "Pick an answer to continue."
    total = len(questions) + 1
    context = _flow(
        {
            "log": log,
            "question": question,
            "answer": answer,
            "n": n,
            "total": total,
            "progress": round(n / total * 100),
            "back_url": reverse("app:checkin", args=[log.pk, n - 1]) if n > 1 else reverse("app:home"),
            "scale": range(1, 11),
            "other_option": OTHER_OPTION,
            "coach_name": _coach_first_name(request.athlete),
            "error": error,
        }
    )
    return TemplateResponse(request, "app/checkin.html", context)


@athlete_required
def checkin_summary(request, log_id):
    log = _log(request, log_id)
    if log.finished:
        return redirect("app:player", log.pk, 1)
    if request.method == "POST":
        skip = request.POST.get("action") == "skip"
        if skip:
            log.answers.all().delete()
        log.checkin_skipped = skip
        log.save(update_fields=["checkin_skipped"])
        return redirect("app:player", log.pk, 1)
    questions = _questions(request.athlete)
    total = len(questions) + 1
    context = _flow(
        {
            "log": log,
            "answers": list(log.answers.all()),
            "n": total,
            "total": total,
            "back_url": reverse("app:checkin", args=[log.pk, len(questions)])
            if questions
            else reverse("app:home"),
            "exercise_count": log.exercises.count(),
        }
    )
    return TemplateResponse(request, "app/checkin_summary.html", context)


# ---------------------------------------------------------------- session player


def _time_unit(p):
    """Timed work is entered in minutes when it's prescribed in whole minutes of 2 or more."""
    seconds = p.duration_seconds if p else None
    return "min" if seconds and seconds >= 120 and seconds % 60 == 0 else "s"


def _set_rows(se, p, unit):
    logged = {s.set_number: s for s in se.sets.all()}
    planned = (len(p.overrides) or p.sets) if p else 0
    count = max([planned, *logged.keys(), 1])
    overrides = {o.set_number: o for o in p.overrides} if p else {}
    time_unit = _time_unit(p)
    rows = []
    for number in range(1, count + 1):
        s = logged.get(number)
        o = overrides.get(number)
        if s is not None:
            load = units.from_kg(s.load_kg, unit).normalize() if s.load_kg is not None else ""
            reps = s.reps if s.reps is not None else ""
            seconds = s.duration_seconds
            rir = "" if s.rir is None else str(s.rir)
            done = s.done
        else:
            load, reps, rir, done = "", "", "", False
            seconds = p.duration_seconds if p else None
            if p:
                load_value = o.load_value if o and o.load_value is not None else p.load_value
                kg = sessions.target_kg(p, load_value)
                load = sessions.plate_round(kg, unit) if kg else ""
                reps = (o.reps if o and o.reps is not None else p.reps) or ""
        if seconds is None:
            time = ""
        elif time_unit == "min":
            time = format((seconds / 60), "g")
        else:
            time = seconds
        rows.append(
            {
                "number": number,
                "load": format(load, "f") if load != "" else "",
                "reps": reps,
                "time": time,
                "rir": rir,
                "done": done,
                "placeholder": (o.rep_scheme if o and o.rep_scheme else p.rep_scheme) if p else "",
            }
        )
    return rows, time_unit


def _banner(p, unit):
    if p is None:
        return None
    reps = p.rep_scheme or ("—" if not p.sets else "")
    load = load_text(p.load_basis, p.load_value, unit)
    hint = "prescribed load" if load else ""
    if p.overrides:
        hint = "loads vary by set"
    if p.load_basis == LoadBasis.PERCENT:
        kg = sessions.target_kg(p, p.load_value)
        if kg:
            hint = f"≈ {sessions.plate_round(kg, unit)} {unit} from your {p.max_exercise} max"
            if p.overrides:
                hint = f"loads vary by set · {p.max_exercise} max {units.display(p.max_kg, unit)}"
        else:
            hint = "no max on file — go by feel"
    return {"sets": len(p.overrides) or p.sets, "reps": reps, "load": load, "rir": p.rir, "hint": hint}


@athlete_required
def player(request, log_id, n):
    athlete = request.athlete
    log = _log(request, log_id)
    exercises = list(log.exercises.select_related("exercise__category").prefetch_related("sets"))
    if not exercises:
        return redirect("app:finish", log.pk)
    if not 1 <= n <= len(exercises):
        return redirect("app:player", log.pk, 1)
    unit = athlete.units
    se = exercises[n - 1]
    p = sessions.prescribed(se)
    exercise = se.exercise
    measure = exercise.measure if exercise else (Measure.TIME if p and p.duration_seconds else Measure.REPS)
    rows, time_unit = _set_rows(se, p, unit)
    last = None
    if exercise:
        entries = history.exercise_history(athlete, [exercise.pk], exclude_log=log, limit=1).get(exercise.pk)
        if entries:
            last = history.last_line(entries[0], unit, athlete.today())
    dots = []
    for i, other in enumerate(exercises, start=1):
        sets = list(other.sets.all())
        planned = max(sessions.planned_sets(other), 1)
        dots.append("on" if i == n else "done" if sum(1 for s in sets if s.done) >= planned else "")
    editable = log.editable()
    context = _flow(
        {
            "log": log,
            "se": se,
            "p": p,
            "exercise": exercise,
            "measure": measure,
            "rows": rows,
            "time_unit": time_unit,
            "rir_choices": RIR_CHOICES,
            "banner": _banner(p, unit),
            "custom_fields": p.custom_fields if p else [],
            "last": last,
            "n": n,
            "total": len(exercises),
            "progress": round((n - 1) / len(exercises) * 100 + 5),
            "dots": dots,
            "unit": unit,
            "editable": editable,
            "edit_until": log.finished_at + EDIT_WINDOW if log.finished_at else None,
            "coach_name": _coach_first_name(athlete),
            "prev_url": reverse("app:player", args=[log.pk, n - 1]) if n > 1 else None,
            "next_url": reverse("app:player", args=[log.pk, n + 1])
            if n < len(exercises)
            else (reverse("app:finish", args=[log.pk]) if editable else None),
            "exit_url": reverse("app:pause", args=[log.pk]),
        }
    )
    return TemplateResponse(request, "app/player.html", context)


@athlete_required
@require_POST
def save_set(request, log_id, se_id, number):
    """One set, saved as it's ticked or changed. JSON so the row can retry on failure."""
    log = _log(request, log_id)
    if not log.editable():
        return JsonResponse({"error": "This session can no longer be changed."}, status=409)
    se = get_object_or_404(log.exercises, pk=se_id)
    if not 1 <= number <= 50:
        raise Http404
    form = SetForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": "Check the numbers in this set."}, status=400)
    data = form.cleaned_data
    load = data["load"]
    sessions.save_set(
        se,
        number,
        load_kg=units.to_kg(load, request.athlete.units) if load is not None else None,
        reps=data["reps"],
        duration_seconds=data["duration_seconds"],
        rir=data["rir"],
        done=data["done"],
    )
    return JsonResponse({"saved": True})


@athlete_required
def pause(request, log_id):
    log = _log(request, log_id)
    if log.finished:
        return redirect("app:progress")
    messages.info(request, "Session paused — pick it up any time")
    return redirect(f"{reverse('app:home')}?day={log.date.isoformat()}")


# ---------------------------------------------------------------- post-session and done


def _set_counts(log):
    exercises = list(log.exercises.prefetch_related("sets"))
    done = sum(1 for se in exercises for s in se.sets.all() if s.done)
    planned = sum(max(sessions.planned_sets(se), sum(1 for s in se.sets.all() if s.done)) for se in exercises)
    return len(exercises), done, planned


@athlete_required
def finish(request, log_id):
    log = _log(request, log_id)
    if not log.editable():
        return redirect("app:player", log.pk, 1)
    form = FinishForm(request.POST or None, initial={"rpe": log.session_rpe, "comment": log.comment})
    if request.method == "POST" and form.is_valid():
        first_time = not log.finished
        sessions.finish(log, form.cleaned_data["rpe"], form.cleaned_data["comment"])
        if first_time:
            return redirect("app:done", log.pk)
        messages.success(request, "Changes saved")
        return redirect("app:progress")
    count = log.exercises.count()
    context = _flow(
        {
            "log": log,
            "form": form,
            "rpe": form["rpe"].value(),
            "scale": range(1, 11),
            "coach_name": _coach_first_name(request.athlete),
            "back_url": reverse("app:player", args=[log.pk, count]) if count else reverse("app:home"),
            "issues": list(log.issues.all()),
        }
    )
    return TemplateResponse(request, "app/finish.html", context)


@athlete_required
def issue(request, log_id):
    log = _log(request, log_id)
    form = IssueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.athlete, report.session_log = request.athlete, log
        report.save()
        from apps.dashboard import alerts

        alerts.issue_reported(report)
        response = TemplateResponse(request, "app/_issue_list.html", {"issues": list(log.issues.all())})
        hx.toast(response, f"Sent — {_coach_first_name(request.athlete)} has been notified", "good")
        return hx.trigger_after_swap(response, closeModal=True)
    template = "app/_issue_modal.html" if request.method == "GET" else "app/_issue_form.html"
    response = TemplateResponse(
        request, template, {"log": log, "form": form, "coach_name": _coach_first_name(request.athlete)}
    )
    if request.method == "POST":
        hx.retarget(response, "#issueForm", "outerHTML")
    return response


@athlete_required
def done(request, log_id):
    athlete = request.athlete
    log = _log(request, log_id)
    if not log.finished:
        return redirect(_resume_url(log))
    exercise_count, sets_done, sets_planned = _set_counts(log)
    today = athlete.today()
    next_date = history.next_session_date(athlete, today)
    top_sets = sum(
        1 for se in log.exercises.prefetch_related("sets") if any(s.done and s.load_kg for s in se.sets.all())
    )
    context = _flow(
        {
            "log": log,
            "exercise_count": exercise_count,
            "sets_done": sets_done,
            "sets_planned": sets_planned,
            "streak": history.streak(athlete, today),
            "next_date": next_date,
            "today": today,
            "top_sets": top_sets,
            "coach_name": _coach_first_name(athlete),
        }
    )
    return TemplateResponse(request, "app/done.html", context)


# ---------------------------------------------------------------- progress and profile


@athlete_required
def progress(request):
    athlete = request.athlete
    unit = athlete.units
    today = athlete.today()
    prs = [
        {
            "name": pr["name"],
            "heaviest": history.set_text(pr["heaviest"], unit),
            "heaviest_ago": history.ago(pr["heaviest_date"], today),
            "e1rm": history.e1rm_text(pr["e1rm"], unit) if pr["e1rm"] else "",
            "e1rm_ago": history.ago(pr["e1rm_date"], today) if pr["e1rm_date"] else "",
        }
        for pr in history.lifetime_prs(athlete)
    ]
    recent = list(athlete.session_logs.finished().order_by("-date", "-finished_at")[:5])
    now = timezone.now()
    context = {
        "tab": "progress",
        "prs": prs,
        "recent": [{"log": log, "editable": log.editable(now)} for log in recent],
    }
    return TemplateResponse(request, "app/progress.html", context)


@athlete_required
def profile(request):
    athlete = request.athlete
    specs = metric_specs(athlete.gym)
    current = current_metrics(athlete, specs)
    rows = []
    for spec in specs:
        m = current[spec.key]
        if m["value"] in (None, ""):
            value = None
        elif spec.kind == "weight":
            value = units.display(m["kg"], athlete.units)
        elif spec.kind == "height":
            value = f"{format(m['value'].normalize(), 'f')} cm"
        else:
            value = m["value"]
        rows.append({"label": spec.label, "value": value})
    context = {
        "tab": "profile",
        "rows": rows,
        "missing_count": len(missing_metrics(athlete, specs)),
        "coach_name": _coach_first_name(athlete),
    }
    return TemplateResponse(request, "app/profile.html", context)
