from django.http import HttpResponse
from django.template.response import TemplateResponse

from apps import hx
from apps.accounts.access import coach_required


def _coach_page(request, panel, title, template="coach/placeholder.html", **extra):
    # Placeholder pages that prove the coach shell; real screens arrive in later phases.
    return TemplateResponse(request, template, {"panel": panel, "title": title, **extra})


@coach_required
def dashboard(request):
    return _coach_page(request, "dashboard", "Dashboard")


PROGRAMMING_TAB_LABELS = {"templates": "Templates", "weeks": "Saved weeks", "sessions": "Saved sessions"}


@coach_required
def programming_placeholder(request, ptab):
    return _coach_page(
        request,
        "programming",
        "Programming",
        template="coach/programming/placeholder.html",
        ptab=ptab,
        ptab_label=PROGRAMMING_TAB_LABELS[ptab],
    )


@coach_required
def ping(request):
    """Tiny HTMX round trip used by the shells and tests: returns a fragment and fires a toast."""
    response = HttpResponse('<span class="chip chip--good" id="pingResult">HTMX is wired</span>')
    return hx.toast(response, "Server replied", "good")
