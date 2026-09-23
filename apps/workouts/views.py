from django.template.response import TemplateResponse

from apps.accounts.access import athlete_required


def _app_page(request, tab, title):
    # Placeholder athlete screens that prove the phone shell. Real views arrive in phase 4.
    return TemplateResponse(request, "app/placeholder.html", {"tab": tab, "title": title})


@athlete_required
def home(request):
    return _app_page(request, "week", "This week")


@athlete_required
def progress(request):
    return _app_page(request, "progress", "Your progress")


@athlete_required
def messages(request):
    return _app_page(request, "coach", "Coach")


@athlete_required
def profile(request):
    return _app_page(request, "profile", "Profile & metrics")
