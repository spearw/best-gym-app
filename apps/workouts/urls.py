from django.urls import path

from apps.accounts import views as account_views
from apps.messaging import views as mv

from . import views

app_name = "app"

urlpatterns = [
    path("", views.home, name="home"),
    path("sessions/<int:session_id>/start/", views.start, name="start"),
    path("log/<int:log_id>/", views.resume, name="resume"),
    path("log/<int:log_id>/checkin/<int:n>/", views.checkin, name="checkin"),
    path("log/<int:log_id>/checkin/done/", views.checkin_summary, name="checkin_summary"),
    path("log/<int:log_id>/exercise/<int:n>/", views.player, name="player"),
    path("log/<int:log_id>/sets/<int:se_id>/<int:number>/", views.save_set, name="save_set"),
    path("log/<int:log_id>/pause/", views.pause, name="pause"),
    path("log/<int:log_id>/finish/", views.finish, name="finish"),
    path("log/<int:log_id>/issue/", views.issue, name="issue"),
    path("log/<int:log_id>/done/", views.done, name="done"),
    path("progress/", views.progress, name="progress"),
    path("coach/", mv.athlete_tab, name="messages"),
    path("coach/thread/", mv.athlete_thread, name="message_thread"),
    path("coach/send/", mv.athlete_send, name="message_send"),
    path("profile/", views.profile, name="profile"),
    path("welcome/", account_views.welcome_metrics, name="welcome_metrics"),
    path("profile/numbers/", account_views.update_numbers, name="numbers"),
    path("welcome/done/", account_views.welcome_done, name="welcome_done"),
]
