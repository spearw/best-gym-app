from django.urls import path

from apps.accounts import views as account_views

from . import views

app_name = "coach"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("athletes/", views.athletes, name="athletes"),
    path("programming/", views.programming, name="programming"),
    path("settings/", account_views.settings_page, name="settings"),
    path("invites/new/", account_views.invite_new, name="invite_new"),
    path("invites/", account_views.invite_create, name="invite_create"),
    path("invites/pending/", account_views.invite_list, name="invite_list"),
    path("invites/<int:pk>/revoke/", account_views.invite_revoke, name="invite_revoke"),
    path("ping/", views.ping, name="ping"),
]
