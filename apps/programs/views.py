"""Settings › Week types: a gym's own week types (name, description, colour, order).

A week type that anything uses (program weeks, template weeks, session logs) is
archived instead of deleted, so past weeks keep their label and colour. "In use" is
worked out from every model that points at WeekType, so new ones are covered
automatically."""

from django.db import transaction
from django.db.models import Max
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST

from apps import hx
from apps.accounts.access import coach_required
from apps.exercises.forms import NameForm, save_pending_names

from .models import HEX_COLOUR, WeekType

NAME_LENGTH = WeekType._meta.get_field("name").max_length
DESCRIPTION_LENGTH = WeekType._meta.get_field("description").max_length


def usage_count(week_type):
    """How many rows anywhere point at this week type."""
    total = 0
    for rel in WeekType._meta.get_fields(include_hidden=True):
        if rel.auto_created and not rel.concrete and (rel.one_to_many or rel.one_to_one):
            total += rel.related_model._base_manager.filter(**{rel.field.name: week_type}).count()
    return total


def card_context(gym):
    rows = list(WeekType.objects.filter(gym=gym))
    for wt in rows:
        wt.uses = usage_count(wt)
    return {
        "active": [w for w in rows if not w.archived],
        "archived": [w for w in rows if w.archived],
        "name_max": NAME_LENGTH,
        "description_max": DESCRIPTION_LENGTH,
    }


def render_card(request, message=None, kind=""):
    response = TemplateResponse(request, "programs/_week_types.html", card_context(request.coach.gym))
    return hx.toast(response, message, kind) if message else response


def _colour(value):
    value = (value or "").strip().upper()
    return value if HEX_COLOUR.fullmatch(value) else None


def _name_form(request, instance=None):
    data = {"name": request.POST.get(f"name_{instance.pk}" if instance else "name", "")}
    return NameForm(
        data,
        model=WeekType,
        gym=request.coach.gym,
        max_length=NAME_LENGTH,
        what="week type",
        instance=instance,
    )


def save_pending_edits(request):
    """Every request from the card carries each row's on-screen name, description and
    colour (name_<id>, description_<id>, colour_<id>). Save valid changes before acting."""
    gym, post = request.coach.gym, request.POST
    save_pending_names(WeekType, gym, post, NAME_LENGTH)
    for wt in WeekType.objects.filter(gym=gym):
        changed = []
        colour = _colour(post.get(f"colour_{wt.pk}"))
        if colour and colour != wt.colour:
            wt.colour = colour
            changed.append("colour")
        if f"description_{wt.pk}" in post:
            description = " ".join(post[f"description_{wt.pk}"].split())
            if len(description) <= DESCRIPTION_LENGTH and description != wt.description:
                wt.description = description
                changed.append("description")
        if changed:
            wt.save(update_fields=changed)


@coach_required
@require_POST
def add(request):
    save_pending_edits(request)
    form = _name_form(request)
    colour = _colour(request.POST.get("colour")) or "#6B7280"
    if not form.is_valid():
        return render_card(request, form.errors["name"][0], "bad")
    gym = request.coach.gym
    order = (WeekType.objects.filter(gym=gym).aggregate(m=Max("order"))["m"] or 0) + 1
    WeekType.objects.create(gym=gym, name=form.cleaned_data["name"], colour=colour, order=order)
    return render_card(request, f"Week type “{form.cleaned_data['name']}” added", "good")


@coach_required
@require_POST
def update(request, pk):
    """Saves name, description and colour as they're edited. Nothing is redrawn unless
    something was invalid, so the coach's typing and queued clicks aren't disturbed."""
    wt = get_object_or_404(WeekType, pk=pk, gym=request.coach.gym)
    form = _name_form(request, instance=wt)
    colour = _colour(request.POST.get(f"colour_{wt.pk}"))
    description = " ".join(request.POST.get(f"description_{wt.pk}", wt.description).split())
    problem = None
    if not form.is_valid():
        problem = form.errors["name"][0]
    elif colour is None:
        problem = "Pick a colour like #2E9E5B"
    elif len(description) > DESCRIPTION_LENGTH:
        problem = f"Keep descriptions to {DESCRIPTION_LENGTH} characters."
    if problem:
        return hx.retarget(render_card(request, problem, "bad"), "#weekTypes", "outerHTML")
    wt.name, wt.colour, wt.description = form.cleaned_data["name"], colour, description
    wt.save(update_fields=["name", "colour", "description"])
    # The pill preview uses the colour, so redraw just that row's pill out of band.
    response = TemplateResponse(request, "programs/_week_type_pill.html", {"wt": wt, "oob": True})
    return hx.toast(response, "Week type saved")


@coach_required
@require_POST
def move(request, pk, direction):
    save_pending_edits(request)
    gym = request.coach.gym
    with transaction.atomic():
        rows = list(WeekType.objects.select_for_update().filter(gym=gym, archived=False))
        ids = [r.pk for r in rows]
        if pk not in ids or direction not in ("up", "down"):
            raise Http404
        i = ids.index(pk)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(rows):
            rows[i], rows[j] = rows[j], rows[i]
            for order, row in enumerate(rows):
                if row.order != order:
                    row.order = order
                    row.save(update_fields=["order"])
    return render_card(request)


@coach_required
@require_POST
def remove(request, pk):
    save_pending_edits(request)
    wt = get_object_or_404(WeekType, pk=pk, gym=request.coach.gym, archived=False)
    uses = usage_count(wt)
    if uses:
        wt.archived = True
        wt.save(update_fields=["archived"])
        return render_card(
            request,
            f"“{wt.name}” is used by {uses} week{'s' if uses != 1 else ''}, so it was "
            "archived: it leaves the pickers, and those weeks keep it.",
        )
    name = wt.name
    wt.delete()
    return render_card(request, f"Deleted “{name}”")


@coach_required
@require_POST
def restore(request, pk):
    save_pending_edits(request)
    wt = get_object_or_404(WeekType, pk=pk, gym=request.coach.gym, archived=True)
    wt.archived = False
    wt.order = (WeekType.objects.filter(gym=wt.gym, archived=False).aggregate(m=Max("order"))["m"] or 0) + 1
    wt.save(update_fields=["archived", "order"])
    return render_card(request, f"“{wt.name}” restored", "good")
