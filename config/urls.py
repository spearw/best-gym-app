from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as account_views
from apps.dashboard import pwa

urlpatterns = [
    path("", account_views.index, name="index"),
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
    path("accounts/", include("apps.accounts.urls")),
    path("join/<str:token>/", account_views.join),  # short invite links; same view as accounts:join
    path("coach/", include("apps.dashboard.urls")),
    path("app/", include("apps.workouts.urls")),
    path("admin/", admin.site.urls),
]
