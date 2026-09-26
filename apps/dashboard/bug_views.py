"""The "Report a bug" button in both headers. Reports go to the Django admin for now
(dashboard.BugReport); the page, browser and screen size come along automatically."""

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.template.response import TemplateResponse

from apps import hx
from apps.ratelimit import by_user, rate_limit

from .models import BugReport


class BugForm(forms.Form):
    description = forms.CharField(
        max_length=4000,
        label="What went wrong?",
        widget=forms.Textarea(
            attrs={"rows": 5, "placeholder": "What you did, what you expected, and what happened instead."}
        ),
        error_messages={"required": "Describe the problem first."},
    )
    page = forms.CharField(max_length=500, required=False, widget=forms.HiddenInput)
    screen = forms.CharField(max_length=40, required=False, widget=forms.HiddenInput)


def _side(request):
    """Which app the button was pressed in: as the header says, else from the profile."""
    side = request.GET.get("side") or request.POST.get("side")
    if side in BugReport.Side.values:
        return side
    return BugReport.Side.COACH if request.user.coach_profile else BugReport.Side.ATHLETE


def _gym(user):
    profile = user.coach_profile or user.athlete_profile
    return profile.gym if profile else None


@login_required
@rate_limit("bug", 20, 60 * 60, key=by_user)
def bug_report(request):
    side = _side(request)
    if request.method == "POST":
        form = BugForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            BugReport.objects.create(
                user=request.user,
                gym=_gym(request.user),
                side=side,
                description=data["description"].strip(),
                page=data["page"],
                screen=data["screen"],
                user_agent=request.headers.get("User-Agent", "")[:400],
            )
            response = hx.toast(HttpResponse(""), "Thanks — your bug report was sent", "good")
            return hx.trigger_after_swap(response, closeModal=True)
    else:
        # HTMX sends the page the button was pressed on; a plain request has the Referer.
        page = (request.htmx.current_url if request.htmx else "") or request.headers.get("Referer", "")
        form = BugForm(initial={"page": page[:500]})
    return TemplateResponse(request, "partials/bug_modal.html", {"form": form, "side": side})
