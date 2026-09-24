"""Coach-side athlete screens: the roster, the athlete detail shell and its Metrics tab."""

from decimal import Decimal

from django import forms
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps import hx
from apps.workouts.models import CheckinQuestion

from . import units
from .access import coach_required
from .emails import send_metrics_reminder
from .forms import InputClassMixin
from .metrics import current_metrics, metric_specs, missing_metrics, save_metrics, spec_for
from .models import Athlete, MaxUpdates, MeasurementSource, YearsTraining
from .views import _invite_list_context

DETAIL_TABS = [
    ("overview", "Overview", 7),
    ("program", "Program", None),
    ("sessions", "Sessions", None),
    ("metrics", "Metrics", None),
    ("messages", "Messages", None),
]


def coach_athlete(request, pk):
    """One of this coach's own, active athletes, or 404."""
    return get_object_or_404(
        Athlete.objects.select_related("user", "gym", "coach__user"),
        pk=pk,
        coach=request.coach,
        archived_at__isnull=True,
    )


@coach_required
def roster(request):
    q = request.GET.get("q", "").strip()
    athletes = request.coach.athletes.filter(archived_at__isnull=True).select_related("user")
    if q:
        athletes = athletes.filter(Q(user__name__icontains=q) | Q(user__email__icontains=q))
    cards = [{"athlete": a, "missing": len(missing_metrics(a))} for a in athletes]
    context = {"panel": "athletes", "title": "Athletes", "cards": cards, "q": q}
    if request.htmx and request.htmx.target == "clientCards":
        return TemplateResponse(request, "coach/_roster_cards.html", context)
    return TemplateResponse(request, "coach/athletes.html", {**context, **_invite_list_context(request)})


def _header_context(request, athlete):
    gym_units = request.coach.gym.units
    specs = metric_specs(athlete.gym)
    metrics = current_metrics(athlete, specs)
    stats = [
        (
            m.exercise.name,
            units.from_kg(metrics[m.key]["kg"], gym_units).normalize() if metrics[m.key]["kg"] else None,
        )
        for m in specs
        if m.exercise is not None
    ]
    return {
        "athlete": athlete,
        "stats": stats,
        "stat_unit": gym_units,
        "tabs": DETAIL_TABS,
        "panel": "athletes",
        "title": athlete.user.name or athlete.user.email,
    }


@coach_required
def athlete_detail(request, pk, tab="overview"):
    athlete = coach_athlete(request, pk)
    if tab == "metrics":
        return athlete_metrics(request, athlete)
    if tab == "messages":
        from apps.messaging.views import coach_tab

        return coach_tab(request, athlete)
    if tab == "sessions":
        from apps.workouts.coach_views import sessions_tab

        return sessions_tab(request, athlete, _header_context(request, athlete))
    phase = dict((key, ph) for key, _label, ph in DETAIL_TABS)[tab]
    label = dict((key, lbl) for key, lbl, _ph in DETAIL_TABS)[tab]
    return TemplateResponse(
        request,
        "coach/athlete/placeholder.html",
        {**_header_context(request, athlete), "tab": tab, "tab_label": label, "phase": phase},
    )


def _metric_cards(request, athlete):
    gym_units = request.coach.gym.units
    specs = metric_specs(athlete.gym)
    current = current_metrics(athlete, specs)
    cards = []
    for spec in specs:
        key, label, kind = spec.key, spec.label, spec.kind
        m = current[key]
        if kind == "weight" and m["kg"] is not None:
            value, unit = units.from_kg(m["kg"], gym_units).normalize(), gym_units
        elif kind == "height" and m["value"] is not None:
            value, unit = m["value"].normalize(), "cm"
        else:
            value, unit = m["value"], ""
        cards.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "unit": unit,
                "date": m["date"],
                "source": m["source"],
                "missing": m["value"] in (None, ""),
            }
        )
    return cards


def _metrics_context(request, athlete):
    recent = sorted(
        [("Bodyweight", e) for e in athlete.bodyweights.all()[:10]]
        + [(e.exercise.name, e) for e in athlete.maxes.select_related("exercise")[:10]],
        key=lambda pair: (pair[1].date, pair[1].created_at),
        reverse=True,
    )[:10]
    gym_units = request.coach.gym.units
    history = [
        {
            "what": what,
            "date": e.date,
            "value": units.display(e.kg, gym_units),
            "source": e.get_source_display(),
        }
        for what, e in recent
    ]
    cards = _metric_cards(request, athlete)
    return {
        "cards": cards,
        "history": history,
        "missing_count": sum(1 for c in cards if c["missing"]),
        "pending_prs": _pending_prs(athlete, gym_units),
        "max_updates_choices": MaxUpdates.choices,
    }


def _pending_prs(athlete, unit):
    from apps.workouts import prs

    return [
        {
            "set_id": c.set_log.pk,
            "exercise": c.exercise.name,
            "load": units.display(c.set_log.load_kg, unit),
            "reps": c.set_log.reps,
            "date": c.set_log.session_exercise.session_log.date,
            "current": units.display(c.current.kg, unit),
        }
        for c in prs.pending(athlete)
    ]


def athlete_metrics(request, athlete):
    questions = CheckinQuestion.objects.for_athlete(athlete).active()
    context = {
        **_header_context(request, athlete),
        **_metrics_context(request, athlete),
        "tab": "metrics",
        "questions": questions,
        "builder_id": "qBuilder",
        "builder_prefix": reverse("coach:athlete_questions", args=[athlete.pk]),
    }
    return TemplateResponse(request, "coach/athlete/metrics.html", context)


class MetricEditForm(InputClassMixin, forms.Form):
    value = forms.DecimalField(min_value=Decimal("1"), max_value=Decimal("1000"), decimal_places=2)
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="As of")

    def __init__(self, *args, kind, unit, athlete, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind, self.athlete = kind, athlete
        if kind == "years":
            self.fields["value"] = forms.ChoiceField(choices=YearsTraining.choices, label="Years training")
            del self.fields["date"]
        else:
            self.fields["value"].label = f"Value ({unit})"
            self.fields["value"].widget.attrs.update(
                {"inputmode": "decimal", "step": "any", "autofocus": True}
            )
            if kind == "height":
                del self.fields["date"]
            else:
                self.fields["date"].initial = athlete.today()
                self.fields["date"].widget.attrs["max"] = athlete.today().isoformat()

    def clean_date(self):
        date = self.cleaned_data["date"]
        if date > self.athlete.today():
            raise forms.ValidationError("That date is in the future.")
        return date


@coach_required
def metric_edit(request, pk, key):
    athlete = coach_athlete(request, pk)
    spec = spec_for(athlete.gym, key)
    if spec is None:  # not a metric this gym has (e.g. an untracked lift)
        return HttpResponse(status=404)
    label, kind = spec.label, spec.kind
    unit = {"weight": request.coach.gym.units, "height": "cm", "years": ""}[kind]
    form = MetricEditForm(request.POST or None, kind=kind, unit=unit, athlete=athlete)
    if request.method == "POST" and form.is_valid():
        save_metrics(
            athlete,
            {key: form.cleaned_data["value"]},
            source=MeasurementSource.COACH,
            date=form.cleaned_data.get("date"),
            entry_units=request.coach.gym.units,
        )
        response = TemplateResponse(
            request,
            "coach/athlete/_metrics_panel.html",
            {**_header_context(request, athlete), **_metrics_context(request, athlete), "oob_header": True},
        )
        response = hx.retarget(response, "#metricsPanel", "outerHTML")
        hx.trigger(response, toast={"message": f"{label} saved", "kind": "good"})
        return hx.trigger_after_swap(response, closeModal=True)
    return TemplateResponse(
        request,
        "coach/athlete/_metric_modal.html",
        {"athlete": athlete, "form": form, "label": label, "key": key},
    )


@coach_required
@require_POST
def remind_metrics(request, pk):
    athlete = coach_athlete(request, pk)
    missing = missing_metrics(athlete)
    if not missing:
        return hx.toast(HttpResponse(""), f"{athlete.user.get_short_name()} has filled in everything")
    send_metrics_reminder(request, athlete, missing)
    return hx.toast(HttpResponse(""), f"Reminder emailed to {athlete.user.get_short_name()}", "good")


@coach_required
@require_POST
def max_updates(request, pk):
    athlete = coach_athlete(request, pk)
    value = request.POST.get("max_updates")
    if value in MaxUpdates.values:
        athlete.max_updates = value
        athlete.save(update_fields=["max_updates"])
        from apps.dashboard import alerts

        alerts.sync_prs(athlete)
    name = athlete.user.get_short_name()
    message = (
        f"Session PRs now update {name}'s maxes automatically"
        if athlete.max_updates == MaxUpdates.AUTO
        else f"You'll review {name}'s session PRs before their maxes change"
    )
    return hx.toast(athlete_metrics(request, athlete), message, "good")


@coach_required
@require_POST
def pr_decide(request, pk, set_id):
    """Use a session PR as the working max, or keep the current one."""
    from apps.workouts import prs

    athlete = coach_athlete(request, pk)
    candidate = prs.pending_set(athlete, set_id)
    if candidate is None:
        return hx.toast(athlete_metrics(request, athlete), "That PR has already been handled", "err")
    lift = candidate.exercise.name
    if request.POST.get("decision") == "use":
        prs.accept(athlete, candidate)
        message = f"{lift} max is now {units.display(candidate.set_log.load_kg, request.coach.gym.units)}"
    else:
        prs.dismiss(athlete, candidate)
        message = f"Kept {lift} at {units.display(candidate.current.kg, request.coach.gym.units)}"
    from apps.dashboard import alerts

    alerts.sync_prs(athlete)
    return hx.toast(athlete_metrics(request, athlete), message, "good")


@coach_required
def athlete_default_tab(request, pk):
    return redirect("coach:athlete_tab", pk=pk, tab="overview")
