from django.urls import path

from . import views

app_name = "coach"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("athletes/", views.athletes, name="athletes"),
    path("programming/", views.programming, name="programming"),
    path("settings/", views.settings_page, name="settings"),
    path("ping/", views.ping, name="ping"),
]
