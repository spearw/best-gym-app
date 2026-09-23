from django.http import HttpResponse
from django.template.response import TemplateResponse


def index(request):
    # Phase 1 replaces this with login and a redirect by profile (coach or athlete).
    return TemplateResponse(request, "index.html")


def _coach_page(request, panel, title):
    # Placeholder pages that prove the coach shell and hx-boost navigation.
    # Real views arrive in later phases and add CoachRequiredMixin.
    return TemplateResponse(request, "coach/placeholder.html", {"panel": panel, "title": title})


def dashboard(request):
    return _coach_page(request, "dashboard", "Dashboard")


def athletes(request):
    return _coach_page(request, "athletes", "Athletes")


def programming(request):
    return _coach_page(request, "programming", "Programming")


def settings_page(request):
    return _coach_page(request, "settings", "Settings")


def ping(request):
    """Tiny HTMX round trip used by the shells and tests: returns a fragment and fires a toast."""
    response = HttpResponse('<span class="chip chip--good" id="pingResult">HTMX is wired</span>')
    response["HX-Trigger"] = '{"toast": {"message": "Server replied", "kind": "good"}}'
    return response
