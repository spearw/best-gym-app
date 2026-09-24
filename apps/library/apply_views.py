"""The apply preview on an athlete's Program tab, and saving a board into the library.

While a coach previews, the draft (source, days, tag-slot mode, where it starts,
publish-now, which week is shown) lives in the Django session under the athlete's id.
Every control re-posts the draft and the editor is redrawn with dashed "ghost" weeks
from apply.plan(); nothing is written until Confirm. Cancel just drops the draft.
"""

import datetime

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts.access import coach_required
from apps.accounts.coach_views import coach_athlete
from apps.accounts.models import Athlete
from apps.programs.prescriptions import summary
from apps.programs.program_views import _program, _week, render_editor

from . import apply, services
from .models import Template, TemplateKind

SESSION_KEY = "apply_drafts"
APPLYABLE = [TemplateKind.PROGRAM, TemplateKind.WEEK]


def sources(gym):
    return Template.objects.filter(gym=gym, kind__in=APPLYABLE).order_by("kind", "name", "id")


def get_draft(request, athlete):
    return request.session.get(SESSION_KEY, {}).get(str(athlete.pk))


def save_draft(request, athlete, draft):
    drafts = request.session.get(SESSION_KEY, {})
    if draft is None:
        drafts.pop(str(athlete.pk), None)
    else:
        drafts[str(athlete.pk)] = draft
    request.session[SESSION_KEY] = drafts


def new_draft(template, athlete):
    options = apply.placements(athlete)
    return {
        "template": template.pk,
        "days": apply.default_days(template),
        "mode": apply.RECENT,
        "start": options[0].value,
        "publish": False,
        "view": 0,  # the ghost week shown; None shows the real week
    }


def _draft_template(request, draft):
    return Template.objects.filter(pk=draft["template"], gym=request.coach.gym, kind__in=APPLYABLE).first()


def apply_context(request, athlete):
    """Extra context for the program editor while a draft is being previewed."""
    draft = get_draft(request, athlete)
    if not draft:
        return {}
    template = _draft_template(request, draft)
    if template is None:
        save_draft(request, athlete, None)
        return {}
    unit = request.coach.gym.units
    planned = apply.plan(template, athlete, draft["days"], draft["mode"])
    placement = apply.placement_for(athlete, draft["start"])
    program = placement.program
    start = placement.start_date
    ghosts = []
    for i, week in enumerate(planned):
        first_order = placement.start_order if program else 0
        ghosts.append(
            {
                "index": i,
                "planned": week,
                "label": f"Wk {first_order + i + 1}",
                "start": start + apply.WEEK * i,
            }
        )
    view = draft.get("view")
    shown = ghosts[view] if isinstance(view, int) and 0 <= view < len(ghosts) else None
    board = None
    if shown:
        board = []
        for offset in range(7):
            session = shown["planned"].days.get(offset)
            items = []
            if session:
                for slot, exercise in session.exercises:
                    items.append(
                        {
                            "name": exercise.name,
                            "summary": summary(slot, unit, list(slot.set_overrides.all())),
                            "tags": list(slot.tags.all()) if slot.is_tag else [],
                        }
                    )
            board.append(
                {"date": shown["start"] + datetime.timedelta(days=offset), "session": session, "items": items}
            )
    st_sessions = sum(w.session_count for w in planned)
    tag_slots = sum(1 for w in planned for s in w.days.values() for slot, _e in s.exercises if slot.is_tag)
    week_start = athlete.gym.week_start
    day_names = [datetime.date(2024, 1, 1 + (week_start + i) % 7).strftime("%a") for i in range(7)]
    return {
        "applying": True,
        "draft": draft,
        "apply_template": template,
        "apply_sources": sources(request.coach.gym),
        "apply_days": [{"offset": i, "name": day_names[i], "on": i in draft["days"]} for i in range(7)],
        "apply_placements": apply.placements(athlete),
        "apply_placement": placement,
        "ghosts": ghosts,
        "ghost_shown": shown,
        "ghost_board": board,
        "apply_summary": {
            "weeks": len(planned),
            "sessions": st_sessions,
            "tag_slots": tag_slots,
            "habits": template.habits.count(),
            "replaced": len(placement.replaced),
            "moved": len(placement.moved),
            "new_program": program is None,
        },
        "replaced_ids": {w.pk for w in placement.replaced},
        "moved_ids": {w.pk for w in placement.moved},
    }


def _redraw(request, athlete, message=None, kind=""):
    draft = get_draft(request, athlete)
    week_id = None
    if draft and draft.get("view") is None:
        week_id = draft.get("real_week")
    return render_editor(request, athlete, week_id, message, kind)


# ---------------------------------------------------------------- starting a preview


class StartForm(forms.Form):
    template = forms.ModelChoiceField(queryset=Template.objects.none())
    athlete = forms.ModelChoiceField(queryset=Athlete.objects.none())

    def __init__(self, *args, coach, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = sources(coach.gym)
        self.fields["athlete"].queryset = coach.athletes.filter(archived_at__isnull=True).select_related(
            "user"
        )


@coach_required
def apply_modal(request):
    """From Programming: pick the template (or saved week) and the athlete, then preview."""
    form = StartForm(
        request.POST or None, coach=request.coach, initial={"template": request.GET.get("template")}
    )
    if request.method == "POST" and form.is_valid():
        athlete, template = form.cleaned_data["athlete"], form.cleaned_data["template"]
        save_draft(request, athlete, new_draft(template, athlete))
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("coach:program", args=[athlete.pk])
        messages.info(
            request,
            f"Previewing on {athlete.user.get_short_name()}'s board — nothing is applied until you confirm",
        )
        return response
    athletes = [
        {"athlete": a, "program": _program(a)}
        for a in request.coach.athletes.filter(archived_at__isnull=True).select_related("user")
    ]
    return TemplateResponse(
        request,
        "library/_apply_modal.html",
        {
            "form": form,
            "sources": sources(request.coach.gym),
            "athletes": athletes,
            "chosen": request.GET.get("template", ""),
        },
    )


@coach_required
@require_POST
def apply_start(request, pk):
    """From the athlete's board: "+ Template" or "+ Saved week" starts a preview."""
    athlete = coach_athlete(request, pk)
    kind = TemplateKind.WEEK if request.POST.get("kind") == "week" else TemplateKind.PROGRAM
    template = Template.objects.filter(gym=request.coach.gym, kind=kind).order_by("name", "id").first()
    if template is None:
        what = "saved weeks" if kind == TemplateKind.WEEK else "templates"
        return hx.toast(HttpResponse(status=204), f"No {what} yet — build one under Programming", "err")
    save_draft(request, athlete, new_draft(template, athlete))
    name = athlete.user.get_short_name()
    message = f"Previewing on {name}'s board — nothing is applied until you confirm"
    if not (request.htmx and request.htmx.target == "programEditor"):
        # From the "no program yet" card: there's no board to redraw, so load the page.
        messages.info(request, message)
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("coach:program", args=[athlete.pk])
        return response
    return render_editor(request, athlete, message=message)


@coach_required
@require_POST
def apply_update(request, pk):
    athlete = coach_athlete(request, pk)
    draft = get_draft(request, athlete)
    if not draft:
        return render_editor(request, athlete)
    post = request.POST
    if "template" in post and str(draft["template"]) != post["template"]:
        template = get_object_or_404(sources(request.coach.gym), pk=post["template"])
        draft = new_draft(template, athlete) | {"mode": draft["mode"], "start": draft["start"]}
    else:
        if "day" in post or post.get("days_sent"):
            draft["days"] = sorted({int(d) for d in post.getlist("day") if d.isdigit() and int(d) < 7})
            draft["view"] = 0
        if post.get("mode") in (apply.RECENT, apply.DEFAULTS):
            draft["mode"] = post["mode"]
        if post.get("start"):
            draft["start"] = post["start"]
            draft["view"] = 0
        if "publish_sent" in post:
            draft["publish"] = post.get("publish") == "on"
        if post.get("view", "") != "":
            view = post["view"]
            if view.isdigit():
                draft["view"] = int(view)
            else:
                draft["view"], draft["real_week"] = None, view.removeprefix("week:")
    save_draft(request, athlete, draft)
    return _redraw(request, athlete)


@coach_required
@require_POST
def apply_cancel(request, pk):
    athlete = coach_athlete(request, pk)
    save_draft(request, athlete, None)
    return render_editor(request, athlete, message="Apply cancelled — nothing changed")


@coach_required
@require_POST
def apply_confirm(request, pk):
    athlete = coach_athlete(request, pk)
    draft = get_draft(request, athlete)
    template = _draft_template(request, draft) if draft else None
    if template is None:
        return render_editor(request, athlete, message="Nothing to apply", kind="err")
    n = len(apply.plan(template, athlete, draft["days"], draft["mode"]))
    try:
        program, first, habits_added = apply.confirm(
            athlete, template, draft["days"], draft["mode"], draft["start"], draft["publish"], request.user
        )
    except apply.CannotApply as err:
        return _redraw(request, athlete, str(err), "err")
    save_draft(request, athlete, None)
    state = (
        "published"
        if draft["publish"]
        else f"unpublished — review, then publish to {athlete.user.get_short_name()}"
    )
    message = (
        f"“{template.display_name}” applied — {n} week{'s' if n != 1 else ''} from {first.label}, {state}"
    )
    if habits_added:
        message += f" · {habits_added} habit{'s' if habits_added != 1 else ''} prescribed"
    return render_editor(request, athlete, first.pk, message, "good")


# ---------------------------------------------------------------- saving the board into the library


class SaveForm(forms.Form):
    name = forms.CharField(max_length=80, required=False)
    description = forms.CharField(max_length=200, required=False)


@coach_required
def save_week(request, pk, week_id):
    athlete = coach_athlete(request, pk)
    week = _week(athlete, week_id)
    sessions = services.board_sessions(week)
    if not sessions:
        return hx.toast(HttpResponse(status=204), "This week has no sessions to save", "err")
    form = SaveForm(request.POST or None, initial={"name": f"{week.week_type.name} — {len(sessions)} day"})
    if request.method == "POST" and form.is_valid():
        saved = services.save_week(
            request.coach.gym, request.user, week, form.cleaned_data["name"], form.cleaned_data["description"]
        )
        response = HttpResponse(status=204)
        hx.toast(response, f"“{saved.display_name}” saved — find it under Programming › Weeks", "good")
        return hx.trigger_after_swap(response, closeModal=True)
    return TemplateResponse(
        request,
        "library/_save_modal.html",
        {
            "form": form,
            "what": "week",
            "action": reverse("coach:program_save_week", args=[athlete.pk, week.pk]),
            "summary": {
                "week_type": week.week_type,
                "text": f"{len(sessions)} session{'s' if len(sessions) != 1 else ''} from {week.label}",
            },
        },
    )


@coach_required
def save_program(request, pk):
    athlete = coach_athlete(request, pk)
    program = _program(athlete)
    if program is None or not any(services.board_sessions(w) for w in program.weeks.all()):
        return hx.toast(HttpResponse(status=204), "Nothing to save — this program has no sessions yet", "err")
    name = athlete.user.get_short_name()
    form = SaveForm(
        request.POST or None,
        initial={
            "name": f"{program.name} (from {name})",
            "description": f"Saved from {athlete.user.name or name}'s program",
        },
    )
    if request.method == "POST" and form.is_valid():
        saved = services.save_program(
            request.coach.gym,
            request.user,
            program,
            form.cleaned_data["name"],
            form.cleaned_data["description"],
        )
        response = HttpResponse(status=204)
        hx.toast(
            response,
            f"Saved as “{saved.display_name}” — open it under Programming › Templates to refine",
            "good",
        )
        return hx.trigger_after_swap(response, closeModal=True)
    weeks = sum(1 for w in program.weeks.all() if services.board_sessions(w))
    return TemplateResponse(
        request,
        "library/_save_modal.html",
        {
            "form": form,
            "what": "template",
            "action": reverse("coach:program_save_template", args=[athlete.pk]),
            "summary": {
                "week_type": None,
                "text": f"{weeks} week{'s' if weeks != 1 else ''} with sessions from {program.name}",
            },
        },
    )
