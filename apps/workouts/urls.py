from django.urls import path

from . import views

app_name = "app"

urlpatterns = [
    path("", views.home, name="home"),
    path("progress/", views.progress, name="progress"),
    path("coach/", views.messages, name="messages"),
    path("profile/", views.profile, name="profile"),
]
