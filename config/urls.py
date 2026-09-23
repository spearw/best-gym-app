from django.contrib import admin
from django.urls import include, path

from apps.dashboard import views as dashboard_views

urlpatterns = [
    path("", dashboard_views.index, name="index"),
    path("coach/", include("apps.dashboard.urls")),
    path("app/", include("apps.workouts.urls")),
    path("admin/", admin.site.urls),
]
