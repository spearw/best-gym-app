from django.template.response import TemplateResponse


def _app_page(request, tab, title):
    # Placeholder athlete screens that prove the phone shell. Real views arrive in phase 4.
    return TemplateResponse(request, "app/placeholder.html", {"tab": tab, "title": title})


def home(request):
    return _app_page(request, "week", "This week")


def progress(request):
    return _app_page(request, "progress", "Your progress")


def messages(request):
    return _app_page(request, "coach", "Coach")


def profile(request):
    return _app_page(request, "profile", "Profile & metrics")
