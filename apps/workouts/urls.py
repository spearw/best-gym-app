from django.urls import path

from apps.accounts import views as account_views

from . import views

app_name = "app"

urlpatterns = [
    path("", views.home, name="home"),
    path("progress/", views.progress, name="progress"),
    path("coach/", views.messages, name="messages"),
    path("profile/", views.profile, name="profile"),
    path("welcome/", account_views.welcome_metrics, name="welcome_metrics"),
    path("welcome/done/", account_views.welcome_done, name="welcome_done"),
]
