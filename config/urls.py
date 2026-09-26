from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as account_views
from apps.dashboard import bug_views, pwa

urlpatterns = [
    path("", account_views.index, name="index"),
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
    path("feedback/bug/", bug_views.bug_report, name="bug_report"),
    path("accounts/", include("apps.accounts.urls")),
    path("join/<str:token>/", account_views.join),  # short invite links; same view as accounts:join
    path("coach/", include("apps.dashboard.urls")),
    path("app/", include("apps.workouts.urls")),
    # The admin's sign-in, rate-limited like the site's; listed first so it wins.
    path(f"{settings.ADMIN_PATH}login/", account_views.admin_login),
    path(settings.ADMIN_PATH, admin.site.urls),
]
