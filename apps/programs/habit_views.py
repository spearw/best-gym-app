"""Habits: prescribed by the coach on the athlete's Program tab, ticked by the athlete
on Home (today or yesterday). Rules live in habits.py."""

import datetime

from django import forms
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts.access import athlete_required, coach_required
from apps.accounts.coach_views import coach_athlete

from . import habits
from .models import Habit

EMOJI = ["🍎", "😴", "💧", "🧘", "🚶", "🥩", "🥗", "⚖️", "💪", "📓"]


class HabitForm(forms.ModelForm):
    class Meta:
        model = Habit
        fields = ["name", "emoji", "cadence", "note"]


# ---------------------------------------------------------------- coach


def coach_card_context(athlete):
    today = athlete.today()
    items = [
        {
            "habit": h,
            "streak": habits.streak(h, today),
            "dots": habits.last_seven(h, today),
            "done_today": h.logs.filter(date=today).exists(),
        }
        for h in habits.active(athlete).select_related("source_template")
    ]
    return {"athlete": athlete, "habit_items": items, "cadences": Habit.Cadence.choices, "emoji": EMOJI}


def _coach_card(request, athlete, message=None, kind=""):
    response = TemplateResponse(request, "programs/_habit_card.html", coach_card_context(athlete))
    return hx.toast(response, message, kind) if message else response


@coach_required
@require_POST
def add(request, pk):
    athlete = coach_athlete(request, pk)
    form = HabitForm(request.POST)
    if not form.is_valid():
        return _coach_card(request, athlete, "Give the habit a name", "err")
    d = form.cleaned_data
    habit = habits.prescribe(athlete, d["name"].strip(), d["emoji"], d["cadence"], d["note"].strip())
    if habit is None:
        return _coach_card(
            request, athlete, f"{athlete.user.get_short_name()} already has “{d['name']}”", "err"
        )
    return _coach_card(
        request,
        athlete,
        f"Habit prescribed — {athlete.user.get_short_name()} sees it in their app today",
        "good",
    )


@coach_required
@require_POST
def remove(request, pk, habit_id):
    athlete = coach_athlete(request, pk)
    habit = get_object_or_404(Habit, pk=habit_id, athlete=athlete, archived_at__isnull=True)
    habits.archive(habit)
    return _coach_card(request, athlete, f"Stopped prescribing “{habit.name}” (its history is kept)")


# ---------------------------------------------------------------- athlete


def athlete_card_context(athlete, which="today"):
    today = athlete.today()
    date = today - datetime.timedelta(days=1) if which == "yesterday" else today
    items = habits.for_day(athlete, date)
    return {
        "habit_items": items,
        "habit_day": which,
        "habit_date": date,
        "habits_done": sum(1 for i in items if i["done"] or i["met_for_week"]),
        "has_habits": habits.active(athlete).exists(),
    }


@athlete_required
def athlete_card(request):
    which = "yesterday" if request.GET.get("day") == "yesterday" else "today"
    return TemplateResponse(request, "app/_habits.html", athlete_card_context(request.athlete, which))


@athlete_required
@require_POST
def tick(request, habit_id):
    athlete = request.athlete
    habit = get_object_or_404(Habit, pk=habit_id, athlete=athlete, archived_at__isnull=True)
    which = "yesterday" if request.POST.get("day") == "yesterday" else "today"
    context = athlete_card_context(athlete, which)
    try:
        habits.toggle(habit, context["habit_date"])
    except habits.CannotTick as err:
        return hx.toast(HttpResponse(status=400), str(err), "err")
    return TemplateResponse(request, "app/_habits.html", athlete_card_context(athlete, which))
