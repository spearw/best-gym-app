"""Programming › Templates, Weeks and Sessions, and the template editor.

The editor is one page for all three kinds. Every change goes through services.py and
returns the redrawn editor (#tplEditor) with a toast, like the program editor. Lookups
are always scoped to the coach's gym.
"""

from django import forms
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts.access import coach_required
from apps.accounts.forms import InputClassMixin
from apps.exercises.models import Exercise, Tag
from apps.programs.forms import MAX_CUSTOM_FIELDS, MAX_SETS, PrescriptionForm, set_rows_initial
from apps.programs.models import WeekType
from apps.programs.prescriptions import summary
from apps.programs.program_views import rail_context

from . import services
from .models import (
    HABIT_EMOJI,
    Cadence,
    SlotKind,
    Template,
    TemplateHabit,
    TemplateKind,
    TemplateSession,
    TemplateSlot,
    TemplateWeek,
)

KIND_TABS = {"templates": TemplateKind.PROGRAM, "weeks": TemplateKind.WEEK, "sessions": TemplateKind.SESSION}
TAB_FOR_KIND = {v: k for k, v in KIND_TABS.items()}


# ---------------------------------------------------------------- lookups (scoped to the gym)


def _template(request, pk):
    return get_object_or_404(Template, pk=pk, gym=request.coach.gym)


def _tweek(request, template, week_id):
    return get_object_or_404(TemplateWeek.objects.select_related("template"), pk=week_id, template=template)


def _tsession(request, template, session_id):
    return get_object_or_404(
        TemplateSession.objects.select_related("week"), pk=session_id, week__template=template
    )


def _slot(request, template, slot_id):
    return get_object_or_404(
        TemplateSlot.objects.select_related("session__week", "exercise"),
        pk=slot_id,
        session__week__template=template,
    )


def _exercise(request, pk):
    return get_object_or_404(Exercise, pk=pk, gym=request.coach.gym, archived=False)


# ---------------------------------------------------------------- stats shown on cards and the editor


def stats(template):
    weeks = list(template.weeks.all())
    sessions = [s for w in weeks for s in w.sessions.all()]
    slots = [sl for s in sessions for sl in s.slots.all()]
    return {
        "weeks": len(weeks),
        "sessions": len(sessions),
        "slots": len(slots),
        "tag_slots": sum(1 for sl in slots if sl.kind == SlotKind.TAG),
        "habits": len(template.habits.all()),
        "calendar_weeks": -(-len(sessions) // template.sessions_per_week) if sessions else 0,
    }


def _prefetched(queryset):
    return queryset.prefetch_related(
        Prefetch("weeks", TemplateWeek.objects.select_related("week_type")),
        "weeks__sessions__slots__exercise",
        "weeks__sessions__slots__tags",
        "weeks__sessions__slots__set_overrides",
        "habits",
    ).annotate(uses=Count("applications", distinct=True))


# ---------------------------------------------------------------- list pages


@coach_required
def library_page(request, ptab):
    kind = KIND_TABS[ptab]
    templates = list(_prefetched(Template.objects.filter(gym=request.coach.gym, kind=kind)))
    cards = []
    for t in templates:
        st = stats(t)
        first = t.weeks.all()[0] if st["weeks"] else None
        names = []
        if kind == TemplateKind.SESSION and first:
            for s in first.sessions.all()[:1]:
                names = [
                    f"[{sl.tags.all()[0].name}]" if sl.is_tag and sl.tags.all() else sl.exercise.name
                    for sl in s.slots.all()
                ]
        cards.append({"template": t, "stats": st, "first": first, "names": names})
    context = {"panel": "programming", "title": "Programming", "ptab": ptab, "kind": kind, "cards": cards}
    return TemplateResponse(request, "library/list.html", context)


@coach_required
@require_POST
def new(request, ptab):
    template = services.new_template(request.coach.gym, KIND_TABS[ptab], request.user)
    return redirect("coach:template_edit", template.pk)


# ---------------------------------------------------------------- the editor


def editor_context(request, template):
    template = _prefetched(Template.objects.filter(pk=template.pk)).get()
    unit = request.coach.gym.units
    weeks = []
    for w in template.weeks.all():
        sessions = [
            {
                "session": s,
                "items": [
                    {"slot": sl, "summary": summary(sl, unit, list(sl.set_overrides.all()))}
                    for sl in s.slots.all()
                ],
            }
            for s in w.sessions.all()
        ]
        weeks.append({"week": w, "sessions": sessions})
    gym = request.coach.gym
    in_use = {w["week"].week_type_id for w in weeks}
    return {
        "template": template,
        "weeks": weeks,
        "stats": stats(template),
        "week_types": WeekType.objects.filter(gym=gym).filter(Q(archived=False) | Q(pk__in=in_use)),
        "is_program": template.kind == TemplateKind.PROGRAM,
        "is_week": template.kind == TemplateKind.WEEK,
        "is_session": template.kind == TemplateKind.SESSION,
        "back_tab": TAB_FOR_KIND[template.kind],
        "cadences": Cadence.choices,
        "emoji": HABIT_EMOJI,
        "frequencies": range(1, 7),
        "saved_weeks": Template.objects.filter(gym=gym, kind=TemplateKind.WEEK).exists(),
        "saved_sessions": Template.objects.filter(gym=gym, kind=TemplateKind.SESSION).exists(),
    }


def render_editor(request, template, message=None, kind=""):
    response = TemplateResponse(request, "library/_editor.html", editor_context(request, template))
    return hx.toast(response, message, kind) if message else response


@coach_required
def edit(request, pk):
    template = _template(request, pk)
    context = {
        "panel": "programming",
        "title": template.display_name,
        **editor_context(request, template),
        **rail_context(request, template=template),
    }
    return TemplateResponse(request, "library/editor_page.html", context)


@coach_required
def library(request, pk):
    """The rail's list, searched and filtered."""
    template = _template(request, pk)
    return TemplateResponse(request, "programs/_rail_list.html", rail_context(request, template=template))


class MetaForm(forms.Form):
    name = forms.CharField(max_length=80, required=False)
    description = forms.CharField(max_length=200, required=False)
    sessions_per_week = forms.IntegerField(min_value=1, max_value=6, required=False)


@coach_required
@require_POST
def meta(request, pk):
    """Name, description and "written for": saved as they're typed, without a redraw."""
    template = _template(request, pk)
    form = MetaForm(request.POST)
    if not form.is_valid():
        return hx.toast(HttpResponse(status=400), "Check the name and frequency", "err")
    data = form.cleaned_data
    fields = []
    for field in ["name", "description"]:
        if field in request.POST:
            setattr(template, field, " ".join(data[field].split()))
            fields.append(field)
    if data.get("sessions_per_week"):
        template.sessions_per_week = data["sessions_per_week"]
        fields.append("sessions_per_week")
    template.save(update_fields=[*fields, "updated_at"])
    if "sessions_per_week" in fields:
        return render_editor(request, template)  # the "runs N calendar weeks" line changes
    return HttpResponse(status=204)


@coach_required
@require_POST
def delete(request, pk):
    template = _template(request, pk)
    tab, name = TAB_FOR_KIND[template.kind], template.display_name
    template.delete()
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse(f"coach:programming_{tab}")
    from django.contrib import messages

    messages.success(request, f"Deleted “{name}”")
    return response


# ---------------------------------------------------------------- weeks


class AddWeekForm(forms.Form):
    points = forms.DecimalField(required=False, min_value=-50, max_value=50, decimal_places=2)


@coach_required
@require_POST
def week_add(request, pk):
    template = _template(request, pk)
    form = AddWeekForm(request.POST)
    points = form.cleaned_data["points"] if form.is_valid() else None
    week = services.add_week(template, points)
    note = (
        f", percentages +{points.normalize():f}"
        if points and points > 0
        else (f", percentages {points.normalize():f}" if points else "")
    )
    return render_editor(
        request, template, f"Week {week.order + 1} added as a copy of the previous week{note}", "good"
    )


@coach_required
@require_POST
def week_type(request, pk, week_id):
    template = _template(request, pk)
    week = _tweek(request, template, week_id)
    week.week_type = get_object_or_404(WeekType, pk=request.POST.get("week_type"), gym=request.coach.gym)
    week.save(update_fields=["week_type"])
    return render_editor(request, template)


@coach_required
@require_POST
def week_duplicate(request, pk, week_id):
    template = _template(request, pk)
    week = services.duplicate_week(_tweek(request, template, week_id))
    return render_editor(request, template, f"Week {week.order} duplicated", "good")


@coach_required
@require_POST
def week_remove(request, pk, week_id):
    template = _template(request, pk)
    services.remove_week(_tweek(request, template, week_id))
    return render_editor(request, template, "Week removed")


# ---------------------------------------------------------------- sessions


@coach_required
@require_POST
def session_add(request, pk, week_id):
    template = _template(request, pk)
    session = services.add_session(_tweek(request, template, week_id))
    response = render_editor(request, template, f"{session.name} added", "good")
    return hx.trigger(
        response, toast={"message": f"{session.name} added", "kind": "good"}, selectSession=session.pk
    )


@coach_required
@require_POST
def session_rename(request, pk, session_id):
    template = _template(request, pk)
    session = _tsession(request, template, session_id)
    session.name = " ".join(request.POST.get(f"name_{session.pk}", "").split())[:80]
    session.save(update_fields=["name"])
    return HttpResponse(status=204)


@coach_required
@require_POST
def session_remove(request, pk, session_id):
    template = _template(request, pk)
    session = _tsession(request, template, session_id)
    name = session.name or "Session"
    services.remove_session(session)
    return render_editor(request, template, f"Removed {name}")


# ---------------------------------------------------------------- slots


def _target_session(request, template):
    session_id = request.POST.get("session", "")
    return _tsession(request, template, session_id) if session_id.isdigit() else None


@coach_required
@require_POST
def slot_add(request, pk):
    """From the rail's + (the selected session) or a drag onto a session (with an index)."""
    template = _template(request, pk)
    session = _target_session(request, template)
    if session is None:
        return hx.toast(HttpResponse(status=204), "Select a session on the left first", "err")
    exercise = _exercise(request, request.POST.get("exercise"))
    index = request.POST.get("index", "")
    services.add_slot(session, exercise, int(index) if index.isdigit() else None)
    return render_editor(request, template, f"{exercise.name} → {session.name or 'the session'}", "good")


@coach_required
@require_POST
def tag_slot_add(request, pk):
    """A tag slot from the rail's ticked tags; the default is the first exercise with them all."""
    template = _template(request, pk)
    session = _target_session(request, template)
    if session is None:
        return hx.toast(HttpResponse(status=204), "Select a session on the left first", "err")
    tags = list(
        Tag.objects.filter(
            gym=request.coach.gym, pk__in=[t for t in request.POST.getlist("tag") if t.isdigit()]
        )
    )
    if not tags:
        return hx.toast(HttpResponse(status=204), "Tick at least one tag first", "err")
    candidates = Exercise.objects.filter(gym=request.coach.gym, archived=False)
    for tag in tags:
        candidates = candidates.filter(tags=tag)
    default = candidates.order_by("name").first()
    if default is None:
        return hx.toast(
            HttpResponse(status=204), "No exercise carries all of those tags — loosen the filter", "err"
        )
    services.add_slot(session, default, tags=tags)
    names = ", ".join(t.name for t in tags)
    return render_editor(request, template, f"Tag slot [{names}] added — default {default.name}", "good")


@coach_required
@require_POST
def slot_move(request, pk, slot_id):
    template = _template(request, pk)
    slot = _slot(request, template, slot_id)
    target = _target_session(request, template) or slot.session
    index = request.POST.get("index", "")
    services.move_slot(slot, target, int(index) if index.isdigit() else target.slots.count())
    return render_editor(request, template)


@coach_required
@require_POST
def slot_remove(request, pk, slot_id):
    template = _template(request, pk)
    slot = _slot(request, template, slot_id)
    name = slot.exercise.name if slot.kind == SlotKind.EXERCISE else "Tag slot"
    services.remove_slot(slot)
    response = render_editor(request, template, f"Removed {name}")
    response = hx.retarget(response, "#tplEditor", "outerHTML")
    return hx.trigger_after_swap(response, closeModal=True)


class SlotKindForm(forms.Form):
    """What the slot is: a fixed exercise, or tags plus a default that carries them all."""

    kind = forms.ChoiceField(choices=SlotKind.choices)
    exercise = forms.ModelChoiceField(queryset=Exercise.objects.none(), required=False)
    default = forms.ModelChoiceField(queryset=Exercise.objects.none(), required=False)
    tags = forms.ModelMultipleChoiceField(queryset=Tag.objects.none(), required=False)

    def __init__(self, *args, gym, **kwargs):
        super().__init__(*args, **kwargs)
        exercises = Exercise.objects.filter(gym=gym, archived=False)
        self.fields["exercise"].queryset = exercises
        self.fields["default"].queryset = exercises
        self.fields["tags"].queryset = Tag.objects.filter(gym=gym)

    def clean(self):
        data = super().clean()
        if data.get("kind") == SlotKind.EXERCISE:
            if not data.get("exercise"):
                self.add_error("exercise", "Pick an exercise.")
            data["chosen"], data["tags"] = data.get("exercise"), []
        else:
            tags, default = list(data.get("tags") or []), data.get("default")
            if not tags:
                self.add_error("tags", "Pick at least one tag.")
            elif not default or not {t.pk for t in tags} <= set(default.tags.values_list("pk", flat=True)):
                self.add_error("default", "Pick a default that carries every tag.")
            data["chosen"], data["tags"] = default, tags
        return data


def _slot_modal_context(request, template, slot, form, kind_form):
    unit = request.coach.gym.units
    raw_sets = form["sets"].value()
    sets = int(raw_sets) if str(raw_sets).isdigit() and 1 <= int(raw_sets) <= MAX_SETS else slot.sets
    gym = request.coach.gym
    exercises = list(
        Exercise.objects.filter(gym=gym, archived=False).select_related("category").prefetch_related("tags")
    )
    for e in exercises:
        e.tag_ids = [t.pk for t in e.tags.all()]
    tag_ids = [int(t) for t in (kind_form["tags"].value() or []) if str(t).isdigit()]
    return {
        "template": template,
        "slot": slot,
        "rx": slot,
        "form": form,
        "kind_form": kind_form,
        "kind": kind_form["kind"].value() or slot.kind,
        "exercise_id": int(kind_form["exercise"].value() or slot.exercise_id),
        "default_id": int(kind_form["default"].value() or slot.exercise_id),
        "tag_ids": tag_ids,
        "exercises": exercises,
        "tags": Tag.objects.filter(gym=gym),
        "unit": unit,
        "max_sets": MAX_SETS,
        "sets_initial": sets,
        "parent_values": {
            "reps": form["rep_scheme"].value() or "",
            "load": str(form["load_value"].value() or ""),
        },
        "max_custom": MAX_CUSTOM_FIELDS,
        "custom_fields": slot.custom_fields or [],
        "set_rows": set_rows_initial(slot, unit),
    }


@coach_required
def slot_edit(request, pk, slot_id):
    template = _template(request, pk)
    slot = _slot(request, template, slot_id)
    unit = request.coach.gym.units
    gym = request.coach.gym
    if request.method == "POST":
        form = PrescriptionForm(request.POST, unit=unit)
        kind_form = SlotKindForm(request.POST, gym=gym)
        if form.is_valid() and kind_form.is_valid():
            slot.kind = kind_form.cleaned_data["kind"]
            slot.exercise = kind_form.cleaned_data["chosen"]
            form.save(slot)
            slot.tags.set(kind_form.cleaned_data["tags"])
            response = render_editor(request, template, "Slot updated", "good")
            response = hx.retarget(response, "#tplEditor", "outerHTML")
            return hx.trigger_after_swap(response, closeModal=True)
        context = _slot_modal_context(request, template, slot, form, kind_form)
        context["custom_fields"] = [
            {"key": k, "value": v}
            for k, v in zip(request.POST.getlist("cf_key"), request.POST.getlist("cf_value"), strict=False)
        ]
        context["set_rows"] = [
            {"reps": r, "load": v}
            for r, v in zip(request.POST.getlist("set_reps"), request.POST.getlist("set_load"), strict=False)
        ]
        return TemplateResponse(request, "library/_slot_modal.html", context)
    form = PrescriptionForm(initial=PrescriptionForm.initial_for(slot, unit), unit=unit)
    kind_form = SlotKindForm(
        initial={
            "kind": slot.kind,
            "exercise": slot.exercise_id,
            "default": slot.exercise_id,
            "tags": [t.pk for t in slot.tags.all()],
        },
        gym=gym,
    )
    return TemplateResponse(
        request, "library/_slot_modal.html", _slot_modal_context(request, template, slot, form, kind_form)
    )


# ---------------------------------------------------------------- habits


class HabitForm(InputClassMixin, forms.ModelForm):
    class Meta:
        model = TemplateHabit
        fields = ["name", "emoji", "cadence", "note"]


@coach_required
@require_POST
def habit_add(request, pk):
    template = _template(request, pk)
    form = HabitForm(request.POST)
    if not form.is_valid():
        return hx.toast(HttpResponse(status=204), "Give the habit a name", "err")
    d = form.cleaned_data
    services.add_habit(template, d["name"], d["emoji"], d["cadence"], d["note"])
    return render_editor(request, template, "Habit added to the template", "good")


@coach_required
@require_POST
def habit_remove(request, pk, habit_id):
    template = _template(request, pk)
    get_object_or_404(TemplateHabit, pk=habit_id, template=template).delete()
    return render_editor(request, template, "Habit removed")


# ---------------------------------------------------------------- the library: pick and save


@coach_required
def pick(request, pk, kind):
    """The "+ From saved week / session" picker. `week_id` (for sessions) says where it goes."""
    template = _template(request, pk)
    wanted = TemplateKind.WEEK if kind == "week" else TemplateKind.SESSION
    items = _prefetched(Template.objects.filter(gym=request.coach.gym, kind=wanted).exclude(pk=template.pk))
    context = {
        "template": template,
        "kind": kind,
        "items": [
            {"template": t, "stats": stats(t), "first": t.weeks.all()[0] if t.weeks.all() else None}
            for t in items
        ],
        "week_id": request.GET.get("week", ""),
    }
    return TemplateResponse(request, "library/_pick_modal.html", context)


@coach_required
@require_POST
def pick_use(request, pk, kind, source_id):
    template = _template(request, pk)
    wanted = TemplateKind.WEEK if kind == "week" else TemplateKind.SESSION
    saved = get_object_or_404(Template, pk=source_id, gym=request.coach.gym, kind=wanted)
    if kind == "week":
        week = services.add_saved_week(template, saved)
        message = f"“{saved.display_name}” added as week {week.order + 1}"
    else:
        week = _tweek(request, template, request.POST.get("week"))
        services.add_saved_session(week, saved)
        message = f"“{saved.display_name}” added to week {week.order + 1}"
    response = render_editor(request, template, message, "good")
    response = hx.retarget(response, "#tplEditor", "outerHTML")
    return hx.trigger_after_swap(response, closeModal=True)


class SaveForm(InputClassMixin, forms.Form):
    name = forms.CharField(max_length=80, required=False)
    description = forms.CharField(max_length=200, required=False, label="Description (optional)")


@coach_required
def save_part(request, pk, what, part_id):
    """Save a template week (what="week") or session (what="session") to the library."""
    template = _template(request, pk)
    if what == "week":
        part = _tweek(request, template, part_id)
        suggested = f"{template.display_name} — week {part.order + 1}"
    else:
        part = _tsession(request, template, part_id)
        suggested = part.name or template.display_name
    form = SaveForm(request.POST or None, initial={"name": suggested})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        gym, by = request.coach.gym, request.user
        if what == "week":
            saved = services.save_template_week(gym, by, part, d["name"], d["description"])
            where = "Weeks"
        else:
            saved = services.save_session(gym, by, part, d["name"], d["description"])
            where = "Sessions"
        response = HttpResponse(status=204)
        hx.toast(response, f"“{saved.display_name}” saved — find it under Programming › {where}", "good")
        return hx.trigger_after_swap(response, closeModal=True)
    context = {
        "form": form,
        "what": what,
        "action": reverse("coach:template_save_part", args=[template.pk, what, part.pk]),
        "summary": _part_summary(what, part),
    }
    return TemplateResponse(request, "library/_save_modal.html", context)


def _part_summary(what, part):
    def plural(n, word):
        return f"{n} {word}{'s' if n != 1 else ''}"

    if what == "week":
        sessions = list(part.sessions.all())
        slots = sum(s.slots.count() for s in sessions)
        return {
            "week_type": part.week_type,
            "text": f"{plural(len(sessions), 'session')} · {plural(slots, 'exercise slot')}",
        }
    return {"week_type": None, "text": plural(part.slots.count(), "exercise slot")}
